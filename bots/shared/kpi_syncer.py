"""
KPI Syncer - Periodically push bot KPIs to backend API
"""

import asyncio
import httpx
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class KPISyncer:
    """Sync local KPI tracker data to backend API"""
    
    def __init__(self, bot_id: str, api_base: str = "http://localhost:8000"):
        self.bot_id = bot_id
        self.api_base = api_base
        self.endpoint = f"{api_base}/api/bots/{bot_id}/kpi/update"
    
    async def sync(self, kpi_data: Dict[str, Any]) -> bool:
        """
        Push KPI data to backend API
        
        Args:
            kpi_data: Dict with keys like total_trades, winning_trades, win_rate, etc.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(self.endpoint, json=kpi_data)
                
                if response.status_code == 200:
                    logger.debug(f"KPI sync successful for bot {self.bot_id}")
                    return True
                else:
                    logger.warning(
                        f"KPI sync failed for bot {self.bot_id}: "
                        f"HTTP {response.status_code} - {response.text}"
                    )
                    return False
        except Exception as e:
            logger.error(f"KPI sync error for bot {self.bot_id}: {e}")
            return False
    
    async def sync_from_alpha_tracker(self, kpi_tracker) -> bool:
        """
        Sync KPIs from AlphaBot's KPITracker
        
        Args:
            kpi_tracker: Instance of alpha.kpi_tracker.KPITracker
        """
        try:
            kpi_data = {
                "total_trades": kpi_tracker.total_trades(),
                "winning_trades": sum(1 for t in kpi_tracker._trades if t.pnl > 0),
                "losing_trades": sum(1 for t in kpi_tracker._trades if t.pnl <= 0),
                "total_pnl": round(kpi_tracker.total_pnl(), 2),
                "realized_pnl": round(kpi_tracker.realized_pnl(), 2),
                "win_rate": round(kpi_tracker.win_rate(), 4),
                "max_drawdown": round(kpi_tracker.max_drawdown(), 4),
                "sharpe_ratio": round(kpi_tracker.sharpe_ratio(), 4),
                "strategy_metrics": {
                    "trades": kpi_tracker.total_trades(),
                }
            }
            return await self.sync(kpi_data)
        except Exception as e:
            logger.error(f"Failed to extract alpha KPIs: {e}")
            return False
    
    async def sync_from_mm_tracker(self, kpi_tracker) -> bool:
        """
        Sync KPIs from MarketMakerBot's MMKPITracker
        
        Args:
            kpi_tracker: Instance of market_maker.kpi_tracker.MMKPITracker
        """
        try:
            # Approximate winning/losing trades from equity curve
            winning = 0
            losing = 0
            if len(kpi_tracker.equity_curve) > 1:
                for i in range(1, len(kpi_tracker.equity_curve)):
                    delta = kpi_tracker.equity_curve[i] - kpi_tracker.equity_curve[i-1]
                    if delta > 0:
                        winning += 1
                    elif delta < 0:
                        losing += 1
            
            total_trades = winning + losing
            win_rate = winning / total_trades if total_trades > 0 else 0.0
            
            kpi_data = {
                "total_trades": total_trades,
                "winning_trades": winning,
                "losing_trades": losing,
                "total_pnl": round(kpi_tracker._realized_pnl, 2),
                "realized_pnl": round(kpi_tracker._realized_pnl, 2),
                "win_rate": round(win_rate, 4),
                "max_drawdown": round(kpi_tracker.max_drawdown(), 4),
                "strategy_metrics": {
                    "total_fills": kpi_tracker.total_fills,
                    "bid_fills": kpi_tracker.bid_fills,
                    "ask_fills": kpi_tracker.ask_fills,
                    "spread_pnl": round(kpi_tracker.total_spread_pnl, 2),
                }
            }
            return await self.sync(kpi_data)
        except Exception as e:
            logger.error(f"Failed to extract MM KPIs: {e}")
            return False


class KPISyncWorker:
    """Background worker that periodically syncs KPIs"""
    
    def __init__(
        self,
        bot_id: str,
        sync_interval: int = 30,
        api_base: str = "http://localhost:8000"
    ):
        self.bot_id = bot_id
        self.sync_interval = sync_interval
        self.syncer = KPISyncer(bot_id, api_base)
        self.tracker = None  # Will be set by caller
        self.tracker_type = None  # "alpha" or "mm"
        self._running = False
    
    def set_tracker(self, tracker, tracker_type: str):
        """Set the KPI tracker and its type"""
        self.tracker = tracker
        self.tracker_type = tracker_type  # "alpha" or "mm"
    
    async def run(self):
        """Start the background sync worker"""
        if not self.tracker:
            logger.error("KPISyncWorker: no tracker set")
            return
        
        self._running = True
        logger.info(
            f"KPISyncWorker started for bot {self.bot_id} "
            f"(interval={self.sync_interval}s, type={self.tracker_type})"
        )
        
        while self._running:
            try:
                await asyncio.sleep(self.sync_interval)
                
                if self.tracker_type == "alpha":
                    await self.syncer.sync_from_alpha_tracker(self.tracker)
                elif self.tracker_type == "mm":
                    await self.syncer.sync_from_mm_tracker(self.tracker)
                else:
                    logger.warning(f"Unknown tracker type: {self.tracker_type}")
                    
            except asyncio.CancelledError:
                logger.info("KPISyncWorker cancelled")
                break
            except Exception as e:
                logger.error(f"Error in KPISyncWorker: {e}")
    
    def stop(self):
        """Stop the background worker"""
        self._running = False
