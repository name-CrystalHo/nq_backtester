<!-- Use this file to provide workspace-specific custom instructions to Copilot. For more details, visit https://code.visualstudio.com/docs/copilot/copilot-customization#_use-a-githubcopilotinstructionsmd-file -->

## Important Data Paths
- **NinjaTrader CSV Source**: `C:\Users\cryst\Documents\NinjaTrader 8\db\replay.csv\`
  - Directory structure: `replay.csv\{INSTRUMENT}\{YYYYMMDD}.csv`
  - Example: `replay.csv\NQ SEP25\20250617.csv`
  - Contains both L1 (trade) and L2 (order book) data
  
- **Parquet Storage**: `storage/parquet/{INSTRUMENT}/`
  - Example: `storage/parquet/NQ SEP25/20250617.parquet`
  - Each file contains ~6M L1 records + ~10M L2 records

## Project Status

- [x] Verify that the copilot-instructions.md file in the .github directory is created.

- [x] Clarify Project Requirements
	<!-- High-performance Python tick data backtester with full order book simulation, NinjaTrader CSV conversion to Parquet, realistic fill simulation with market impact modeling -->

- [x] Scaffold the Project
	<!-- Created backtester package structure with data layer (converter, loader, order_book) -->

- [ ] Customize the Project
	<!-- Create remaining modules: engine, strategies, metrics, and example scripts -->

- [ ] Install Required Extensions
	<!-- No specific extensions required -->

- [ ] Compile the Project
	<!-- Install dependencies and verify imports -->

- [ ] Create and Run Task
	<!-- Create example backtest task -->

- [ ] Launch the Project
	<!-- Run example backtest -->

- [ ] Ensure Documentation is Complete
	<!-- Verify README and documentation -->