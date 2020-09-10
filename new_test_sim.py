import numpy as np
from math import log
from numpy import array
from numpy import argmax
from collections import deque, defaultdict
from tqdm import tqdm
import torch
from cache_model_train import DeepCache,Decoder,Decoder_lstm,Encoder,TimeDistributed
from new_lecar import LeCaR
import csv
import glob
import os
import argparse
from embed_lstm_32 import ByteEncoder
from sklearn.neighbors import KernelDensity
import pandas as pd



def create_inout_sequences(input_x,tw):
    L = input_x.shape[0]
    x = torch.zeros(1,L,2)
    x[0] = input_x[0:]  
    return x

def beam_search_decoder(data, k):
	sequences = [[list(), 0.0]]
	# walk over each step in sequence
	for row in data:
		all_candidates = list()
		# expand each current candidate
		for i in range(len(sequences)):
			seq, score = sequences[i]
			for j in range(len(row)):
				candidate = [seq + [j], score - log(row[j])]
				all_candidates.append(candidate)
		# order all candidates by score
		ordered = sorted(all_candidates, key=lambda tup:tup[1])
		# select k best
		sequences = ordered[:k]
	return sequences

def get_prefetch_addresses(prefetch, k) :
    prefetch = [x.squeeze(0).squeeze(0) for x in prefetch] #convert to (n_bytes,256) 
    data = beam_search_decoder(prefetch, k) #return list (list(addr_bytes), scoore)
    top_addresses_bytes = [seq[0] for seq in data] #store only addresses, remove scores
    # convert bytes [b1,b2,b3,b4] to hex string'0x11223344'
    top_k_addresses = []
    for addr in top_addresses_bytes :
        top_k_addresses.append(''.join(format(x, '02x') for x in addr))
    top_k_addresses = ['0x'+str(s) for s in top_k_addresses]
  
    return top_k_addresses


def get_test_data_from_list(addresses,pcs,window_size):
   
    df = pd.DataFrame(list(zip(pcs, addresses)), 
                   columns =['PC', 'Address']) 
    df['Address'] = df['Address'].apply(int, base=16)
    df['PC'] = df['PC'].apply(int, base=16)
    pc = torch.tensor(df['PC'].astype(np.float32)).unsqueeze(1)
    addr = torch.tensor(df['Address'].astype(np.float32)).unsqueeze(1)
    input_x = torch.cat([pc,addr], dim = -1)
    x = create_inout_sequences(input_x,window_size)
    return x

def get_embeddings(addresses,pcs,deepcache):

    input = get_test_data_from_list(addresses,pcs,len(addresses))
    pc      = input[:,:,0:1] 
    address = input[:,:,1:2] # Address value in decimal
    pc_embed = deepcache.get_embed_pc(pc) # Convert decimal address to 4 byte embeddings using pretrained embeddings
    addr_embed = deepcache.get_embed_addr(address)
    # time distributed MLP because we need to apply it on every element of the sequence
    embeddings_pc = deepcache.time_distributed_encoder_mlp(pc_embed) # Convert 4byte embedding to a single address embedding using an MLP
    embeddings_address = deepcache.time_distributed_encoder_mlp(addr_embed)
    # concat pc and adress emeddings
    embeddings = torch.cat([embeddings_pc,embeddings_address] ,dim=-1)

    return embeddings

def get_freq_rec(probs, dist_vector,deepcache):

    freq_rec = deepcache.get_freq_rec(probs,dist_vector) # get freq and rec estimate from prediced probs and distribution vector
    freq = freq_rec[:,0]
    rec = freq_rec[:,1]
    return freq,rec

def get_dist(input, deepcache):
    dist_vector = deepcache.get_distribution_vector(input)
    return dist_vector

def get_prefetch(misses_address,misses_pc,deepcache):

    hidden_cell = (torch.zeros(1, 1, deepcache.hidden_size), # reinitialise hidden state for each new sample
                            torch.zeros(1, 1, deepcache.hidden_size))
    embeddings = get_embeddings(misses_address,misses_pc,deepcache)
    _,hidden_cell = deepcache.lstm(embeddings, hidden_cell)
    probs,_ = deepcache.lstm_decoder(hidden_cell[0])
    return probs


def test_cache_sim(cache_size, ads, pcs, misses_window, miss_history_length):
    hit_rates = []
    deepcache = torch.load("checkpoints/deep_cache.pt")
    lecar = LeCaR(cache_size)
    print('Total Batches: {}'.format(int(len(ads)/1000)))
    for j in range(int(len(ads)/1000)):
        emb_size = 40
        hidden_size = 40
        cache_address = []
        # cache_frequency = []
        # cache_recency = []
        cache_pc = []
        num_hit, num_miss,total_miss = 0, 0, 0
        miss_addresses = []
        pc_misses = []
        rec = None
        freq = None
        cache_stats = {} # dict that stores the elements in cache as keys and their freq and rec as value in tuple
        if j >= 5 :
            break 
        try:
            addresses = ads[j*1000:(j+1)*1000]
        except:
            addresses = ads[j*1000:]
        for i in tqdm(range(len(addresses))):
            address = addresses[i]
            pc = pcs[i]

            #print(f'Request: {address} \nCache {list(cache_stats.keys())} \nFreq {[x for x,y in list(cache_stats.values())]}\nRec {[y for x,y in list(cache_stats.values())]}')

            if address in list(cache_stats.keys()):
                # print('HITTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTT')
                # If address is in cache increment the num_hit
                num_hit += 1
                continue

            elif len(list(cache_stats.keys())) < cache_size: # If address is not in cache and the cache is not full yet then increment the num_miss 
                cache_address.append(address)
                cache_pc.append(pc)
                cache_stats[address] = (np.random.randint(0, 5), np.random.randint(0, 5))
    
                num_miss += 1
                total_miss+=1
                miss_addresses.append(address)
                pc_misses.append(pc)
                if num_miss == miss_history_length: # Calculate freq and rec for every 10 misses
                    num_miss = 0
                    if len(miss_addresses) >= miss_history_length:
                        prefetch = get_prefetch(miss_addresses[-misses_window:],pc_misses[-misses_window:],deepcache)
                        ## Add those top 5 probs thing here [we need the top 5 address]
                    else:
                        prefetch = get_prefetch(miss_addresses,pc_misses,deepcache)

                    prefetch_addresses = get_prefetch_addresses(prefetch, 5)
                    
                    for pref in prefetch_addresses :
                        if len(list(cache_stats.keys())) < cache_size:
                            cache_address.append(pref)
                            cache_pc.append(pref)
                            cache_stats[pref] = (np.random.randint(0, 5), np.random.randint(0, 5))
                        else :
                            e = get_embeddings(list(cache_address),list(cache_pc),deepcache)
                            dist_vector = get_dist(input=e,deepcache=deepcache)
                            probs = get_prefetch(miss_addresses[-misses_window:],pc_misses[-misses_window:],deepcache)
                            freq,rec = get_freq_rec(deepcache=deepcache,dist_vector=dist_vector,probs=probs)

                            cach_freqs = [x for x,y in list(cache_stats.values())]
                            cach_reqs = [y for x,y in list(cache_stats.values())]
                            is_miss, evicted, up_cache = lecar.run(list(cache_stats.keys()), cach_freqs, cach_reqs, pref)

                            """ delete address from the list also"""
                            idx = cache_address.index(evicted)
                            del cache_address[idx]
                            del cache_pc[idx]
                            del cache_stats[evicted] # Delete from main cache
                           

                            """ add requested address to main cache and list """
                            cache_stats[pref] = (int(freq.item()*10),int(rec.item()*10))
                            cache_address.append(pref)
                            cache_pc.append(pref)

                       

            else:
                num_miss += 1
                total_miss+=1
                miss_addresses.append(address)
                pc_misses.append(pc)
                done_prefetch = False
                if num_miss == miss_history_length: # Calculate freq and rec for every 10 misses
                    done_prefetch = True
                    num_miss = 0
                    if len(miss_addresses) >= miss_history_length:
                        prefetch = get_prefetch(miss_addresses[-misses_window:],pc_misses[-misses_window:],deepcache)
                    else:
                        prefetch = get_prefetch(miss_addresses,pc_misses,deepcache)
                    
                    prefetch_addresses = get_prefetch_addresses(prefetch, 5)
                    

                    for pref in prefetch_addresses :
                        if len(list(cache_stats.keys())) < cache_size:
                            cache_address.append(pref)
                            cache_pc.append(pref)
                            cache_stats[pref] = (np.random.randint(0, 5), np.random.randint(0, 5))
                        else :
                            e = get_embeddings(list(cache_address),list(cache_pc),deepcache)
                            dist_vector = get_dist(input=e,deepcache=deepcache)
                            probs = get_prefetch(miss_addresses[-misses_window:],pc_misses[-misses_window:],deepcache)
                            freq,rec = get_freq_rec(deepcache=deepcache,dist_vector=dist_vector,probs=probs)

                            cach_freqs = [x for x,y in list(cache_stats.values())]
                            cach_reqs = [y for x,y in list(cache_stats.values())]
                            is_miss, evicted, up_cache = lecar.run(list(cache_stats.keys()), cach_freqs, cach_reqs, pref)

                            """ delete address from the list also"""
                            idx = cache_address.index(evicted)
                            del cache_address[idx]
                            del cache_pc[idx]
                            del cache_stats[evicted] # Delete from main cache
                           

                            """ add requested address to main cache and list """
                            cache_stats[pref] = (int(freq.item()*10),int(rec.item()*10))
                            cache_address.append(pref)
                            cache_pc.append(pref)
                        
                        

                if done_prefetch :
                    continue   
                e = get_embeddings(list(cache_address),list(cache_pc),deepcache)
                dist_vector = get_dist(input=e,deepcache=deepcache)
                probs = get_prefetch(miss_addresses[-misses_window:],pc_misses[-misses_window:],deepcache)
                freq,rec = get_freq_rec(deepcache=deepcache,dist_vector=dist_vector,probs=probs)
                ## Add the eviction func here that removes an address from a cache and updates the cache. Also pls return the value of the address removed 
                cach_freqs = [x for x,y in list(cache_stats.values())]
                cach_reqs = [y for x,y in list(cache_stats.values())]
                is_miss, evicted, up_cache = lecar.run(list(cache_stats.keys()), cach_freqs, cach_reqs, address)

                """ delete address from the list also"""
                idx = cache_address.index(evicted)
                del cache_address[idx]
                del cache_pc[idx]
                del cache_stats[evicted] # Delete from main cache
                #print(f'EVICTED : {evicted}\n')
                #print(f'After evicting : {list(cache_stats.keys())}')

                """ add requested address to main cache and list """
                cache_stats[address] = (int(freq.item()*10),int(rec.item()*10))
                cache_address.append(address)
                cache_pc.append(pc)
                #print(f'After adding : {list(cache_stats.keys())}')
                #print(cache_stats)
                

        hitrate = num_hit / (num_hit + total_miss)
        hit_rates.append(hitrate)
        print()
        print('HitRate for batch {}: {}'.format(j+1,hitrate))
        print('---------------------------')
    return np.mean(hit_rates)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description="Test cache")
    parser.add_argument("--r", required=True,
    help="path to test csv file")
    args =  parser.parse_args()

    count = 0
    addresses = []
    pcs = []
    with open(args.r,'r') as file:
        reader = csv.reader(file)
        for row in reader:
            count+=1
            if count == 1:
                continue
            else:
                pcs.append(row[1])
                addresses.append(row[2]) 
    
    print('Count: {}'.format(count))
    print('Testing Started')
    hitrate = test_cache_sim(cache_size=32,ads=addresses,pcs=pcs,misses_window=30,miss_history_length=10)
    print('---------------------------')
    print('Testing Complete')
    print('Average HitRate: {}'.format(hitrate))
    print('---------------------------')