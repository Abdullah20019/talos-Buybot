from web3 import Web3
import json
import time

w3 = Web3(Web3.HTTPProvider('https://arb-mainnet.g.alchemy.com/v2/4fCbrGbjSB3Kc1-o9mf7l'))

v2_abi = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "sender", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "amount0In", "type": "uint256"},
            {"indexed": False, "name": "amount1In", "type": "uint256"},
            {"indexed": False, "name": "amount0Out", "type": "uint256"},
            {"indexed": False, "name": "amount1Out", "type": "uint256"}
        ],
        "name": "Swap",
        "type": "event"
    }
]

pool_addr = Web3.to_checksum_address('0xdaae914e4bae2aae4f536006c353117b90fb37e3')
contract = w3.eth.contract(address=pool_addr, abi=v2_abi)

print(f"Connected to Arbitrum: {w3.is_connected()}")
print(f"Latest block: {w3.eth.block_number}")
print(f"Monitoring pool: {pool_addr}")
print("\nCreating event filter...")

try:
    event_filter = contract.events.Swap.create_filter(from_block='latest')
    print("✅ Filter created successfully!")
    print("\nWaiting for swaps... (checking every 3 seconds)")
    print("Make a swap NOW and watch this screen\n")
    
    check_count = 0
    while check_count < 60:  # Run for 3 minutes
        check_count += 1
        events = event_filter.get_new_entries()
        
        if events:
            print(f"\n🎉 SWAP DETECTED! Found {len(events)} events!")
            for event in events:
                print(f"TX: {event['transactionHash'].hex()}")
                print(f"Block: {event['blockNumber']}")
            break
        else:
            print(f"Check #{check_count}: No swaps yet...", end='\r')
        
        time.sleep(3)
    
    print("\n\nTest completed.")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
