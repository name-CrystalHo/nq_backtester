"""
Basic Backtest Example - Demonstrate the NQ Backtester functionality

This example shows how to:
1. Parse sample market data
2. Run a simple moving average strategy
3. Analyze performance results
"""

import sys
from pathlib import Path

# Add backtester to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtester import Backtester, DataLoader
from backtester.strategies.base_strategy import SimpleMovingAverageStrategy, BuyAndHoldStrategy
from backtester.engine.backtester import BacktestConfig
from backtester.data.converter import convert_csv_to_parquet, parse_timestamp
import pandas as pd
from datetime import datetime
import tempfile
import os


def create_sample_data():
    """Create sample market data in the expected CSV format."""
    
    # Sample data from the original request
    sample_csv_data = """L2;1;20211119000000;5150000;0;5;;16568.5;15
L2;1;20211119000000;5150000;0;6;;16568;1
L2;1;20211119000000;5150000;0;7;;16567.5;31
L2;1;20211119000000;5150000;0;8;;16566.75;60
L2;1;20211119000000;5150000;0;9;;16566.25;1
L1;1;20211119000000;5150000;16571.25;1
L2;1;20211119000000;5150000;2;0;;16572.5;0
L2;1;20211119000000;5150000;0;9;;16566;1
L1;0;20211119000000;5820000;16577.5;1
L2;0;20211119000000;5820000;0;0;;16577.5;1
L2;0;20211119000000;5820000;2;10;;16584;0
L2;0;20211119000000;5820000;0;1;;16578;1
L2;0;20211119000000;5820000;2;10;;16583.75;0
L2;0;20211119000000;5820000;0;1;;16577.75;10"""

    # Add more L1 data for strategy testing (price movements)
    additional_data = []
    base_time = 5820000
    base_price = 16578.0
    
    # Generate some price movement for strategy testing
    for i in range(50):
        time_offset = base_time + (i * 100000)  # 0.1 second intervals
        price = base_price + (i * 0.25 * (1 if i % 4 < 2 else -1))  # Create some oscillation
        
        # Add L1 last price updates
        additional_data.append(f"L1;2;20211119000000;{time_offset};{price:.2f};1")
        
        # Add some L2 updates occasionally
        if i % 5 == 0:
            bid_price = price - 0.5
            ask_price = price + 0.5
            additional_data.append(f"L2;1;20211119000000;{time_offset};1;0;;{bid_price:.2f};10")
            additional_data.append(f"L2;0;20211119000000;{time_offset};1;0;;{ask_price:.2f};10")
    
    # Combine all data
    all_data = sample_csv_data + "\n" + "\n".join(additional_data)
    return all_data


def run_basic_example():
    """Run a basic backtest example."""
    
    print("🚀 NQ Backtester - Basic Example")
    print("=" * 50)
    
    # Create temporary directories for the example
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Setup directory structure
        csv_dir = temp_path / "csv" / "NQ_JUN21"
        csv_dir.mkdir(parents=True)
        parquet_dir = temp_path / "parquet"
        
        # Create sample CSV file
        csv_file = csv_dir / "20211119.csv"
        with open(csv_file, 'w') as f:
            f.write(create_sample_data())
        
        print(f"📁 Created sample data: {csv_file}")
        print(f"📊 Converting CSV to Parquet...")
        
        # Convert CSV to Parquet
        try:
            from backtester.data.converter import convert_single_csv
            result = convert_single_csv(csv_file, parquet_dir)
            print(f"✅ Conversion successful: {result['rows']} records")
            print(f"   L1 records: {result['l1_records']}")
            print(f"   L2 records: {result['l2_records']}")
            print(f"   File size: {result['size_mb']:.2f} MB")
        except Exception as e:
            print(f"❌ Conversion failed: {e}")
            return
        
        # Initialize data loader
        loader = DataLoader(str(parquet_dir))
        
        # Check available data
        instruments = loader.get_available_instruments()
        print(f"\n📈 Available instruments: {instruments}")
        
        if not instruments:
            print("❌ No instruments found")
            return
        
        instrument = instruments[0]
        dates = loader.get_available_dates(instrument)
        print(f"📅 Available dates for {instrument}: {dates}")
        
        if not dates:
            print("❌ No dates found")
            return
        
        # Load sample data
        test_date = dates[0]
        data = loader.load_day(instrument, test_date)
        print(f"\n📊 Loaded {len(data)} records for {test_date}")
        print(f"   Time range: {data['timestamp'].min()} to {data['timestamp'].max()}")
        
        # Show sample records
        print(f"\n📋 Sample records:")
        print(data.head(10).to_string(index=False))
        
        # Run Buy and Hold strategy
        print(f"\n" + "=" * 50)
        print(f"🎯 RUNNING BUY AND HOLD STRATEGY")
        print(f"=" * 50)
        
        config = BacktestConfig(
            initial_capital=100000,
            commission_per_contract=2.50,
            slippage_ticks=0
        )
        
        strategy = BuyAndHoldStrategy(quantity=1)
        backtester = Backtester(strategy, loader, config)
        
        try:
            results = backtester.run(instrument, test_date, test_date)
            results.print_summary("Buy and Hold Results")
        except Exception as e:
            print(f"❌ Buy and Hold backtest failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Run Moving Average strategy
        print(f"\n" + "=" * 50)
        print(f"📈 RUNNING MOVING AVERAGE STRATEGY")
        print(f"=" * 50)
        
        strategy = SimpleMovingAverageStrategy(
            short_window=5,
            long_window=10, 
            quantity=1
        )
        backtester = Backtester(strategy, loader, config)
        
        try:
            results = backtester.run(instrument, test_date, test_date)
            results.print_summary("Moving Average Results")
            
            # Show trade details
            if results.trade_list:
                print(f"\n📋 Trade Details:")
                trade_df = results.get_trade_analysis_df()
                print(trade_df.to_string(index=False))
            
            # Show equity curve sample
            equity_df = results.get_equity_curve_df()
            if not equity_df.empty:
                print(f"\n📊 Equity Curve (first 10 points):")
                print(equity_df.head(10).to_string(index=False))
                
        except Exception as e:
            print(f"❌ Moving Average backtest failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Show backtester summary
        print(f"\n" + "=" * 50)
        print(f"🔍 BACKTESTER SUMMARY")
        print(f"=" * 50)
        
        summary = backtester.get_backtest_summary()
        for key, value in summary.items():
            print(f"{key.replace('_', ' ').title():<25}: {value}")


def test_order_book():
    """Test order book reconstruction."""
    
    print(f"\n" + "=" * 50)
    print(f"📚 ORDER BOOK RECONSTRUCTION TEST")
    print(f"=" * 50)
    
    from backtester.data.order_book import OrderBook
    
    # Create sample L2 events
    sample_events = [
        # Event format: market_data_type, operation, position, price, volume
        {'market_data_type': 1, 'operation': 0, 'position': 0, 'price': 16570.0, 'volume': 10, 'timestamp': datetime.now()},  # Add bid
        {'market_data_type': 1, 'operation': 0, 'position': 1, 'price': 16569.5, 'volume': 15, 'timestamp': datetime.now()},  # Add bid
        {'market_data_type': 0, 'operation': 0, 'position': 0, 'price': 16570.5, 'volume': 8, 'timestamp': datetime.now()},   # Add ask
        {'market_data_type': 0, 'operation': 0, 'position': 1, 'price': 16571.0, 'volume': 12, 'timestamp': datetime.now()},  # Add ask
    ]
    
    order_book = OrderBook()
    
    print("Processing L2 events...")
    for event in sample_events:
        success = order_book.process_l2_event(pd.Series(event))
        print(f"  Event processed: {success}")
    
    print(f"\nOrder Book State:")
    print(f"  Best Bid: {order_book.get_best_bid()}")
    print(f"  Best Ask: {order_book.get_best_ask()}")
    print(f"  Spread: {order_book.get_spread()}")
    print(f"  Mid Price: {order_book.get_mid_price()}")
    
    # Show depth
    bid_depth = order_book.get_bid_depth(3)
    ask_depth = order_book.get_ask_depth(3)
    
    print(f"\nBid Depth (top 3): {bid_depth}")
    print(f"Ask Depth (top 3): {ask_depth}")
    
    # Test liquidity calculation
    liquidity_bid = order_book.get_liquidity_at_price(16569.0, 'bid')
    liquidity_ask = order_book.get_liquidity_at_price(16571.5, 'ask')
    
    print(f"\nLiquidity at 16569.0 (bid): {liquidity_bid}")
    print(f"Liquidity at 16571.5 (ask): {liquidity_ask}")


if __name__ == "__main__":
    try:
        run_basic_example()
        test_order_book()
        
        print(f"\n" + "=" * 50)
        print(f"✅ EXAMPLE COMPLETED SUCCESSFULLY!")
        print(f"=" * 50)
        print(f"""
Next Steps:
1. Convert your NinjaTrader CSV files using: 
   python -m backtester.data.converter convert --source "C:\\...\\replay.csv"

2. Create your own strategy by inheriting from BaseStrategy

3. Run backtests on real market data for validation

4. Compare results with NinjaTrader for accuracy verification
        """)
        
    except Exception as e:
        print(f"\n❌ Example failed: {e}")
        import traceback
        traceback.print_exc()