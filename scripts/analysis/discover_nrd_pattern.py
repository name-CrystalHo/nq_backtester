#!/usr/bin/env python3
"""Discover the actual record format in NRD files"""

import struct
from pathlib import Path

def find_record_pattern(file_path, header_size=32):
    """Try to discover the actual record pattern"""
    
    with open(file_path, 'rb') as f:
        content = f.read()
    
    print(f"\n🔍 Pattern Discovery: {file_path}")
    print(f"   File size: {len(content):,} bytes")
    print(f"   Header size: {header_size} bytes")
    
    data_portion = content[header_size:]
    data_size = len(data_portion)
    
    print(f"   Data portion: {data_size:,} bytes")
    
    # Try to find patterns by looking for repeating structures
    possible_record_sizes = []
    
    # Test record sizes from 16 to 64 bytes
    for record_size in range(16, 65):
        if data_size % record_size == 0:
            num_records = data_size // record_size
            possible_record_sizes.append((record_size, num_records))
    
    print(f"\n📊 Possible record sizes (where data_size % record_size == 0):")
    for size, count in possible_record_sizes[:10]:  # Show top 10
        print(f"   {size:2d} bytes → {count:,} records")
    
    # Test some promising record sizes
    test_sizes = [size for size, _ in possible_record_sizes[:5]]
    
    for record_size in test_sizes:
        print(f"\n🧪 Testing record size: {record_size} bytes")
        
        num_records = data_size // record_size
        
        # Show first few records as hex
        for i in range(min(3, num_records)):
            offset = i * record_size
            record_bytes = data_portion[offset:offset + record_size]
            hex_str = record_bytes.hex()
            print(f"   Record {i+1}: {hex_str}")
            
        # Try common struct formats for this size
        formats_for_size = {
            16: ['<IIII', '<QQ', '<QQII'],
            20: ['<IIIII', '<QII', '<IQI'],
            24: ['<IIIIII', '<QQQ', '<QQII'],
            25: ['<BQQII'],  # Our current format
            28: ['<IIIIIII', '<QQQII'],
            32: ['<IIIIIIII', '<QQQQ', '<QQQQII'],
            40: ['<IIIIIIIIII', '<QQQII', '<QQQQQ'],
        }
        
        if record_size in formats_for_size:
            for fmt in formats_for_size[record_size]:
                try:
                    # Test first record
                    record_bytes = data_portion[0:record_size]
                    if len(record_bytes) == record_size:
                        unpacked = struct.unpack(fmt, record_bytes)
                        print(f"      Format {fmt}: {unpacked}")
                        
                        # Check for reasonable values
                        reasonable = True
                        for val in unpacked:
                            if isinstance(val, int):
                                # Check if any values are suspiciously large (could be corruption)
                                if val > 2**60:  # Arbitrary large number threshold
                                    reasonable = False
                                    break
                        
                        if reasonable:
                            print(f"      ✅ Format {fmt} looks reasonable")
                        else:
                            print(f"      ❌ Format {fmt} has suspicious large values")
                            
                except struct.error as e:
                    print(f"      ❌ Format {fmt} failed: {e}")

def main():
    """Main analysis function"""
    print("🔍 NRD Record Pattern Discovery")
    print("="*50)
    
    # Find NRD files
    nrd_files = list(Path("tests/unit/data/storage/nrd").rglob("*.nrd"))
    
    if not nrd_files:
        print("❌ No NRD files found")
        return
    
    # Test different header sizes on first file
    test_file = nrd_files[0]
    
    for header_size in [32, 40, 64]:
        find_record_pattern(test_file, header_size)

if __name__ == "__main__":
    main()