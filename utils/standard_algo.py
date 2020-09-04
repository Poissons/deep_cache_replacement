from tqdm import tqdm as tqdm 
import numpy as np
from collections import deque, defaultdict
from .lecar import LeCaR
from .arc import ARC
import timeit
import pandas as pd


def getFurthestAccessBlock(C, OPT):
    maxAccessPosition = -1
    maxAccessBlock = -1
    for cached_block in C:
        if len(OPT[cached_block]) is 0:
            return cached_block            
    for cached_block in C:
        if OPT[cached_block][0] > maxAccessPosition:
            maxAccessPosition = OPT[cached_block][0]
            maxAccessBlock = cached_block
    return maxAccessBlock

def Lecar(blocktrace, cache_size) :
    hits = 0
    requests = 0
    lecar = LeCaR(cache_size)
    for i in tqdm(range(len(blocktrace))) :
        block = blocktrace[i]
        requests += 1

        miss, evicted = lecar.request(block)

        if not miss :
            hits += 1
    misses = requests - hits
    hitrate = round(hits / requests, 2)
    return hitrate

def Arc(blocktrace, cache_size) :
    hits = 0
    requests = 0
    lecar = ARC(cache_size)
    for i in tqdm(range(len(blocktrace))) :
        block = blocktrace[i]
        requests += 1

        miss, evicted = lecar.request(block)

        if not miss :
            hits += 1
    misses = requests - hits
    hitrate = round(hits / requests, 2)
    return hitrate

def Belady(blocktrace, frame):
    OPT = defaultdict(deque)

    for i, block in enumerate(tqdm(blocktrace, desc="OPT: building index")):
        OPT[block].append(i)    

    #print ("created OPT dictionary")    

    hit, miss = 0, 0

    C = set()
    seq_number = 0
    for block in tqdm(blocktrace, desc="OPT"):

        if block in C:
            #OPT[block] = OPT[block][1:]
            OPT[block].popleft()
            hit+=1
            #print('hit' + str(block))
            #print(OPT)
        else:
            #print('miss' + str(block))
            miss+=1
            if len(C) == frame:
                fblock = getFurthestAccessBlock(C, OPT)
                assert(fblock != -1)
                C.remove(fblock)
            C.add(block)
            #OPT[block] = OPT[block][1:]
            #print(OPT)
            OPT[block].popleft()

    #print ("hit count" + str(hit_count))
    #print ("miss count" + str(miss_count))
    hitrate = hit / (hit + miss)
    #print(hitrate)
    return hitrate


def LRU(blocktrace, frame):
    
    cache = set()
    recency = deque()
    hit, miss = 0, 0
    
    for i in tqdm(range(len(blocktrace))):
        block = blocktrace[i]
        if block in cache:
            recency.remove(block)
            recency.append(block)
            hit += 1
            
        elif len(cache) < frame:
            cache.add(block)
            recency.append(block)
            miss += 1
            
        else:
            cache.remove(recency[0])
            recency.popleft()
            cache.add(block)
            recency.append(block)
            miss += 1
    
    hitrate = hit / (hit + miss)
    return hitrate

def LFU(blocktrace, frame):
    
    cache = set()
    cache_frequency = defaultdict(int)
    frequency = defaultdict(int)
    
    hit, miss = 0, 0
    
    for block in tqdm(blocktrace):
        frequency[block] += 1
        
        if block in cache:
            hit += 1
            cache_frequency[block] += 1
        
        elif len(cache) < frame:
            cache.add(block)
            cache_frequency[block] += 1
            miss += 1

        else:
            e, f = min(cache_frequency.items(), key=lambda a: a[1])
            cache_frequency.pop(e)
            cache.remove(e)
            cache.add(block)
            cache_frequency[block] = frequency[block]
            miss += 1
    
    hitrate = hit / ( hit + miss )
    return hitrate


def FIFO(blocktrace, frame):
    
    cache = deque(maxlen=frame)
    hit, miss = 0, 0
    
    for block in tqdm(blocktrace, leave=False):
        
        if block in cache:
            hit += 1

        else:
            cache.append(block)
            miss += 1
    
    hitrate = hit / (hit+miss)
    return hitrate


def LIFO(blocktrace, frame):
    
    cache = deque(maxlen=frame)
    hit, miss = 0, 0
    
    for block in tqdm(blocktrace, leave=False):
        if block in cache:
            hit += 1
            
        elif len(cache) < frame:
            cache.append(block)
            miss += 1
        
        else:
            cache.pop()
            cache.append(block)
            miss += 1
            
    hitrate = hit / (hit + miss)
    return hitrate