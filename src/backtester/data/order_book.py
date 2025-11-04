"""
Order Book Reconstructor - Rebuild live order book state from L2 events

Maintains real-time order book state during tick-by-tick replay by processing
L2 events (Add/Update/Remove operations) to reconstruct the full market depth.
"""

from typing import Dict, List, Optional, Tuple
import pandas as pd
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class OrderBook:
    """
    Maintains current order book state from L2 market data events.
    
    Tracks bid and ask sides with multiple price levels, providing
    fast access to market depth and liquidity information.
    """
    
    def __init__(self, max_levels: int = 20):
        """
        Initialize empty order book.
        
        Args:
            max_levels: Maximum number of levels to track on each side
        """
        self.max_levels = max_levels
        self.clear()
    
    def clear(self):
        """Reset order book to empty state (for new day/session)."""
        # Structure: {position: {'price': float, 'volume': int}}
        self.bids: Dict[int, Dict[str, float]] = {}
        self.asks: Dict[int, Dict[str, float]] = {}
        self.last_update = None
        self._best_bid_cache = None
        self._best_ask_cache = None
        self._cache_dirty = True
    
    def process_l2_event(self, record: pd.Series) -> bool:
        """
        Update order book based on L2 operation.
        
        L2 Operations:
        - 0 (Add): Insert new level at specified position
        - 1 (Update): Modify existing level volume
        - 2 (Remove): Delete level (volume becomes 0)
        
        Args:
            record: L2 pandas Series with fields:
                - market_data_type: 0=Ask, 1=Bid  
                - operation: 0=Add, 1=Update, 2=Remove
                - position: Order book level (0=best, 1=second, etc.)
                - price: Price level
                - volume: Volume at level
                - timestamp: Event timestamp
        
        Returns:
            True if event was processed successfully
        """
        try:
            # Determine side (0=Ask, 1=Bid)
            side = 'bids' if record['market_data_type'] == 1 else 'asks'
            operation = record['operation']
            position = record['position']
            price = record['price']
            volume = record['volume']
            
            # Validate inputs
            if pd.isna(operation) or pd.isna(position):
                logger.debug(f"Skipping L2 event with missing operation/position: {record}")
                return False
                
            if position < 0 or position >= self.max_levels:
                logger.debug(f"Position {position} outside valid range [0, {self.max_levels})")
                return False
            
            book_side = getattr(self, side)
            
            if operation == 0 or operation == 1:  # Add or Update
                if price <= 0 or volume < 0:
                    logger.debug(f"Invalid price/volume: price={price}, volume={volume}")
                    return False
                    
                book_side[position] = {
                    'price': float(price),
                    'volume': int(volume)
                }
                
                # Remove level if volume is 0
                if volume == 0:
                    book_side.pop(position, None)
                    
            elif operation == 2:  # Remove
                book_side.pop(position, None)
            
            else:
                logger.debug(f"Unknown operation: {operation}")
                return False
            
            # Update timestamp and invalidate cache
            self.last_update = record['timestamp']
            self._cache_dirty = True
            
            return True
            
        except Exception as e:
            logger.warning(f"Error processing L2 event: {e}, record: {record}")
            return False
    
    def _update_cache(self):
        """Update best bid/ask cache."""
        if not self._cache_dirty:
            return
            
        # Find best bid (highest price = lowest position number)
        if self.bids:
            best_bid_pos = min(self.bids.keys())
            self._best_bid_cache = (
                self.bids[best_bid_pos]['price'],
                self.bids[best_bid_pos]['volume']
            )
        else:
            self._best_bid_cache = (None, None)
        
        # Find best ask (lowest price = lowest position number)  
        if self.asks:
            best_ask_pos = min(self.asks.keys())
            self._best_ask_cache = (
                self.asks[best_ask_pos]['price'],
                self.asks[best_ask_pos]['volume']
            )
        else:
            self._best_ask_cache = (None, None)
            
        self._cache_dirty = False
    
    def get_best_bid(self) -> Tuple[Optional[float], Optional[int]]:
        """
        Get best bid price and volume.
        
        Returns:
            (price, volume) or (None, None) if no bids
        """
        self._update_cache()
        return self._best_bid_cache
    
    def get_best_ask(self) -> Tuple[Optional[float], Optional[int]]:
        """
        Get best ask price and volume.
        
        Returns:
            (price, volume) or (None, None) if no asks
        """
        self._update_cache()
        return self._best_ask_cache
    
    def get_spread(self) -> Optional[float]:
        """
        Calculate bid-ask spread.
        
        Returns:
            Spread in price units, or None if missing bid/ask
        """
        best_bid, _ = self.get_best_bid()
        best_ask, _ = self.get_best_ask()
        
        if best_bid is not None and best_ask is not None:
            return best_ask - best_bid
        return None
    
    def get_mid_price(self) -> Optional[float]:
        """
        Calculate mid-market price.
        
        Returns:
            Mid price, or None if missing bid/ask
        """
        best_bid, _ = self.get_best_bid()
        best_ask, _ = self.get_best_ask()
        
        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / 2.0
        return None
    
    def get_bid_depth(self, levels: int = 10) -> List[Tuple[float, int]]:
        """
        Get bid depth with multiple levels.
        
        Args:
            levels: Number of levels to return
        
        Returns:
            List of (price, volume) tuples, sorted by price descending
        """
        if not self.bids:
            return []
        
        # Sort by position (0 = best bid)
        sorted_positions = sorted(self.bids.keys())[:levels]
        
        result = []
        for pos in sorted_positions:
            bid = self.bids[pos]
            result.append((bid['price'], bid['volume']))
        
        # Sort by price descending (highest bid first)
        result.sort(key=lambda x: x[0], reverse=True)
        return result
    
    def get_ask_depth(self, levels: int = 10) -> List[Tuple[float, int]]:
        """
        Get ask depth with multiple levels.
        
        Args:
            levels: Number of levels to return
        
        Returns:
            List of (price, volume) tuples, sorted by price ascending
        """
        if not self.asks:
            return []
        
        # Sort by position (0 = best ask)
        sorted_positions = sorted(self.asks.keys())[:levels]
        
        result = []
        for pos in sorted_positions:
            ask = self.asks[pos]
            result.append((ask['price'], ask['volume']))
        
        # Sort by price ascending (lowest ask first)
        result.sort(key=lambda x: x[0])
        return result
    
    def get_liquidity_at_price(self, price: float, side: str) -> int:
        """
        Calculate total volume available at or better than specified price.
        
        Args:
            price: Target price level
            side: 'bid' or 'ask'
        
        Returns:
            Total volume available at or better than price
        """
        if side.lower() == 'bid':
            # For bids: "better" means >= price (higher or equal)
            total_volume = 0
            for bid_info in self.bids.values():
                if bid_info['price'] >= price:
                    total_volume += bid_info['volume']
            return total_volume
            
        elif side.lower() == 'ask':
            # For asks: "better" means <= price (lower or equal)
            total_volume = 0
            for ask_info in self.asks.values():
                if ask_info['price'] <= price:
                    total_volume += ask_info['volume']
            return total_volume
            
        else:
            raise ValueError(f"Invalid side: {side}. Must be 'bid' or 'ask'")
    
    def get_volume_at_price(self, price: float, side: str) -> int:
        """
        Get volume at exact price level.
        
        Args:
            price: Exact price level
            side: 'bid' or 'ask'
        
        Returns:
            Volume at exact price, or 0 if not found
        """
        book_side = self.bids if side.lower() == 'bid' else self.asks
        
        for level_info in book_side.values():
            if abs(level_info['price'] - price) < 1e-6:  # Float comparison
                return level_info['volume']
        
        return 0
    
    def get_total_volume(self, side: str, levels: int = None) -> int:
        """
        Calculate total volume on one side of the book.
        
        Args:
            side: 'bid' or 'ask'
            levels: Limit to top N levels, or None for all
        
        Returns:
            Total volume
        """
        book_side = self.bids if side.lower() == 'bid' else self.asks
        
        if not book_side:
            return 0
        
        if levels is None:
            return sum(level['volume'] for level in book_side.values())
        
        # Get top N levels by position
        sorted_positions = sorted(book_side.keys())[:levels]
        return sum(book_side[pos]['volume'] for pos in sorted_positions)
    
    def is_valid(self) -> bool:
        """
        Validate order book state.
        
        Returns:
            True if order book state is valid
        """
        try:
            # Check that best bid < best ask
            best_bid, _ = self.get_best_bid()
            best_ask, _ = self.get_best_ask()
            
            if best_bid is not None and best_ask is not None:
                if best_bid >= best_ask:
                    logger.warning(f"Invalid book: best_bid ({best_bid}) >= best_ask ({best_ask})")
                    return False
            
            # Check that all volumes are positive
            for side_name, side_data in [('bids', self.bids), ('asks', self.asks)]:
                for pos, level in side_data.items():
                    if level['volume'] <= 0:
                        logger.warning(f"Invalid volume in {side_name}[{pos}]: {level['volume']}")
                        return False
                    if level['price'] <= 0:
                        logger.warning(f"Invalid price in {side_name}[{pos}]: {level['price']}")
                        return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Error validating order book: {e}")
            return False
    
    def get_book_snapshot(self) -> Dict:
        """
        Get complete order book snapshot for analysis.
        
        Returns:
            Dictionary with full book state
        """
        return {
            'timestamp': self.last_update,
            'bids': self.get_bid_depth(levels=self.max_levels),
            'asks': self.get_ask_depth(levels=self.max_levels),
            'best_bid': self.get_best_bid(),
            'best_ask': self.get_best_ask(),
            'spread': self.get_spread(),
            'mid_price': self.get_mid_price(),
            'total_bid_volume': self.get_total_volume('bid'),
            'total_ask_volume': self.get_total_volume('ask'),
        }
    
    def __str__(self) -> str:
        """String representation showing top levels."""
        best_bid, bid_vol = self.get_best_bid()
        best_ask, ask_vol = self.get_best_ask()
        spread = self.get_spread()
        
        return (f"OrderBook(best_bid={best_bid}x{bid_vol}, "
                f"best_ask={best_ask}x{ask_vol}, spread={spread})")
    
    def __repr__(self) -> str:
        return self.__str__()