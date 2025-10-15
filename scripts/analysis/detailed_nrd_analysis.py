#!/usr/bin/env python3
"""Detailed analysis of real NRD files to understand format"""

import struct
from pathlib import Path
import datetime

def analyze_nrd_file(file_path):
    """Analyze NRD file with multiple format hypotheses"""
    
    with open(file_path, 'rb') as f:
        content = f.read()
    
    print(f"\n📊 Detailed Analysis: {file_path}")
    print(f"   File size: {len(content):,} bytes")
    
    # Try different header sizes and record formats
    for header_size in [32, 64, 128]:
        print(f"\n🔍 Testing header size: {header_size} bytes")
        
        if len(content) <= header_size:
            print("   ❌ File too small for this header size")
            continue
            
        data_portion = content[header_size:]
        
        # Test different record formats
        formats = [
            ('<BQQII', 25, "B=market_data_type, Q=timestamp, Q=timestamp_offset, I=price, I=volume"),
            ('<QQQII', 28, "Q=timestamp1, Q=timestamp2, Q=timestamp3, I=price, I=volume"),
            ('<QQII', 20, "Q=timestamp, Q=price_volume_combined, I=extra1, I=extra2"),
            ('<IIQII', 20, "I=time1, I=time2, Q=price_volume, I=extra1, I=extra2"),
            ('<QIIIQ', 24, "Q=timestamp, I=price, I=volume, I=extra, Q=offset"),
            ('<dddII', 28, "d=price, d=bid, d=ask, I=volume, I=flags"),
        ]
        
        for fmt, expected_size, description in formats:
            try:
                if len(data_portion) < expected_size * 3:  # Need at least 3 records
                    continue
                    
                print(f"\n   📋 Format: {fmt} ({description})")
                print(f"      Expected record size: {expected_size} bytes")
                
                records_possible = len(data_portion) // expected_size
                print(f"      Possible records: {records_possible:,}")
                
                # Analyze first few records
                for i in range(min(3, records_possible)):
                    offset = i * expected_size
                    record_bytes = data_portion[offset:offset + expected_size]
                    
                    try:
                        unpacked = struct.unpack(fmt, record_bytes)
                        print(f"      Record {i+1}: {unpacked}")
                        
                        # Check if any values look like timestamps
                        for j, val in enumerate(unpacked):
                            if isinstance(val, int) and val > 1000000000:  # Potential timestamp
                                # Try converting as various timestamp formats
                                try:
                                    # Unix timestamp (seconds)
                                    dt1 = datetime.datetime.fromtimestamp(val)
                                    if 2020 <= dt1.year <= 2025:
                                        print(f"        Field {j} as Unix seconds: {dt1}")
                                except:
                                    pass
                                
                                try:
                                    # Unix timestamp (milliseconds) 
                                    dt2 = datetime.datetime.fromtimestamp(val / 1000)
                                    if 2020 <= dt2.year <= 2025:
                                        print(f"        Field {j} as Unix millis: {dt2}")
                                except:
                                    pass
                                
                                try:
                                    # Unix timestamp (microseconds)
                                    dt3 = datetime.datetime.fromtimestamp(val / 1000000)
                                    if 2020 <= dt3.year <= 2025:
                                        print(f"        Field {j} as Unix micros: {dt3}")
                                except:
                                    pass
                                
                                try:
                                    # Unix timestamp (nanoseconds)
                                    dt4 = datetime.datetime.fromtimestamp(val / 1000000000)
                                    if 2020 <= dt4.year <= 2025:
                                        print(f"        Field {j} as Unix nanos: {dt4}")
                                except:
                                    pass
                        
                    except struct.error as e:
                        print(f"      ❌ Struct error: {e}")
                        break
                
            except Exception as e:
                print(f"   ❌ Error with format {fmt}: {e}")

def main():
    """Main analysis function"""
    print("🔍 Detailed NRD Format Analysis")
    print("="*50)
    
    # Find NRD files
    nrd_files = list(Path("tests/unit/data/storage/nrd").rglob("*.nrd"))
    
    if not nrd_files:
        print("❌ No NRD files found")
        return
    
    print(f"📂 Found {len(nrd_files)} NRD files:")
    for f in nrd_files:
        print(f"   - {f}")
    
    # Analyze each file
    for nrd_file in nrd_files[:2]:  # Limit to first 2 files
        analyze_nrd_file(nrd_file)

if __name__ == "__main__":
    main()