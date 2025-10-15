#!/usr/bin/env python3
"""
Analyze real NRD files to understand their binary format.
"""

from src.backtester.data.converters.nrd_to_parquet import NRDToParquetConverter
from pathlib import Path

def analyze_real_nrd_files():
    """Analyze real NRD files to understand the format."""
    converter = NRDToParquetConverter()
    nrd_files = list(Path('tests/unit/data/storage/nrd').rglob('*.nrd'))
    
    print(f"🔍 Found {len(nrd_files)} real NRD files:")
    for f in nrd_files[:3]:
        print(f"   - {f}")
    
    if not nrd_files:
        print("❌ No real NRD files found")
        return
    
    # Analyze the first real NRD file
    nrd_file = nrd_files[0]
    print(f"\n📊 Analyzing: {nrd_file}")
    
    try:
        analysis = converter.analyze_nrd_format(nrd_file)
        
        print(f"   File size: {analysis['file_size']:,} bytes")
        print(f"   Potential header size: {analysis['potential_header_size']} bytes")  
        print(f"   Potential record size: {analysis['potential_record_size']} bytes")
        print(f"   Estimated record count: {analysis['estimated_record_count']:,}")
        print(f"   Header hex (first 32 bytes): {analysis['header_sample_hex']}")
        print(f"   Middle hex (32 bytes): {analysis['middle_sample_hex']}")
        
        # Try to read some raw bytes to understand the format
        with open(nrd_file, 'rb') as f:
            # Skip header and read first few records
            f.seek(analysis['potential_header_size'])
            first_records = f.read(analysis['potential_record_size'] * 3)  # Read 3 records
            
        print(f"   First 3 records hex: {first_records.hex()}")
        
        # Try parsing with current format
        print(f"\n🧪 Testing current struct format '<BQQII' on real data:")
        try:
            import struct
            record_size = struct.calcsize('<BQQII')  # 25 bytes
            
            with open(nrd_file, 'rb') as f:
                f.seek(analysis['potential_header_size'])
                record_bytes = f.read(record_size)
                
            if len(record_bytes) >= record_size:
                record = struct.unpack('<BQQII', record_bytes)
                print(f"   Unpacked: market_data_type={record[0]}, timestamp_raw={record[1]}, "
                      f"timestamp_offset={record[2]}, price_scaled={record[3]}, volume={record[4]}")
                
                # Check if timestamp looks reasonable (should be around current time in nanoseconds)
                current_ns = 1700000000 * 1_000_000_000  # Rough current time in ns
                if record[1] > current_ns * 2:  # Way too big
                    print(f"   ❌ Timestamp {record[1]} seems too large (expected ~{current_ns})")
                else:
                    print(f"   ✅ Timestamp {record[1]} looks reasonable")
            else:
                print(f"   ❌ Not enough bytes to read a record")
                
        except Exception as e:
            print(f"   ❌ Struct parsing failed: {e}")
            
    except Exception as e:
        print(f"❌ Analysis failed: {e}")

if __name__ == "__main__":
    analyze_real_nrd_files()