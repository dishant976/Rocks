"""
Rockateral Public Stats API
FastAPI backend for live collection data including burned tokens.
"""

import os
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="Rockateral Stats API",
    description="Public API for ROCKATERAL NFT collection — live supply, burned tokens, market stats.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== CONFIG ====================
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS", "0x201ed6c53fe2ab2eaa7550a3cff0c06bf410781c")
COLLECTION_SLUG = os.getenv("COLLECTION_SLUG", "rockateral")
RPC_URL = os.getenv("RPC_URL") or os.getenv("ALCHEMY_RPC_URL", "")
OPENSEA_API_KEY = os.getenv("OPENSEA_API_KEY", "")
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "120"))

MINIMAL_ABI = [
    {"inputs": [], "name": "totalSupply", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxSupply", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}], "name": "burn", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "name", "outputs": [{"internalType": "string", "name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType": "address", "name": "owner", "type": "address"}], "name": "balanceOf", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}], "name": "ownerOf", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
]

cache: Dict[str, Any] = {}
cache_timestamps: Dict[str, float] = {}

def is_cache_valid(key: str) -> bool:
    return key in cache_timestamps and (time.time() - cache_timestamps[key]) < CACHE_TTL

def set_cache(key: str, data: Any):
    cache[key] = data
    cache_timestamps[key] = time.time()

def get_web3():
    if not RPC_URL:
        raise HTTPException(status_code=500, detail="No RPC_URL configured")
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        raise HTTPException(status_code=503, detail="Failed to connect to Ethereum RPC")
    return w3

def get_onchain_stats():
    w3 = get_web3()
    contract = w3.eth.contract(address=Web3.to_checksum_address(CONTRACT_ADDRESS), abi=MINIMAL_ABI)
    total_supply = contract.functions.totalSupply().call()
    max_supply = contract.functions.maxSupply().call()
    name = contract.functions.name().call()
    burned = max_supply - total_supply
    return {
        "name": name,
        "contract_address": CONTRACT_ADDRESS,
        "max_supply": max_supply,
        "total_supply": total_supply,
        "burned": burned,
        "burned_percentage": round((burned / max_supply) * 100, 2) if max_supply > 0 else 0,
    }

async def get_opensea_stats():
    if not OPENSEA_API_KEY:
        return None
    url = f"https://api.opensea.io/api/v2/collections/{COLLECTION_SLUG}"
    headers = {"accept": "application/json", "x-api-key": OPENSEA_API_KEY}
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                stats = data.get("collection", data)
                return {
                    "floor_price_eth": float(stats.get("floor_price", 0) or 0),
                    "volume_24h_eth": float(stats.get("stats", {}).get("one_day_volume", 0) or 0),
                    "total_volume_eth": float(stats.get("stats", {}).get("total_volume", 0) or 0),
                    "unique_owners": stats.get("owner_count") or stats.get("stats", {}).get("num_owners"),
                }
        except:
            return None

@app.get("/api/rockateral/stats")
async def get_rockateral_stats(force_refresh: bool = Query(False)):
    cache_key = "rockateral_stats"
    if not force_refresh and is_cache_valid(cache_key):
        data = cache[cache_key]
        data["cached"] = True
        return data

    onchain = get_onchain_stats()
    opensea = await get_opensea_stats()

    combined = {
        **onchain,
        "chain": "ethereum",
        "slug": COLLECTION_SLUG,
        "opensea_url": f"https://opensea.io/collection/{COLLECTION_SLUG}",
        "twitter": "https://x.com/Mr_Anchovy_",
        "website": "https://rockateral.com/",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    if opensea:
        combined.update(opensea)
    else:
        combined["note"] = "Market data limited (add OPENSEA_API_KEY for full stats)"

    response = {"success": True, "data": combined, "cached": False, "last_updated": combined["last_updated"]}
    set_cache(cache_key, response)
    return response


# ==================== WALLET HOLDINGS (NEW) ====================
@app.get("/api/rockateral/wallet/{wallet_address}")
async def get_wallet_holdings(wallet_address: str):
    w3 = get_web3()
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(CONTRACT_ADDRESS),
        abi=MINIMAL_ABI
    )
    try:
        checksum_address = Web3.to_checksum_address(wallet_address)
        balance = contract.functions.balanceOf(checksum_address).call()
        return {
            "success": True,
            "wallet": checksum_address,
            "rockateral_balance": balance,
            "message": f"This wallet holds {balance} ROCKATERAL"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/rockateral/health")
async def health_check():
    return {"status": "healthy", "collection": COLLECTION_SLUG}


@app.get("/")
async def root():
    return {"message": "Rockateral Public API is live 🪨🔥", "docs": "/docs"}