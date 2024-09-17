from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import argparse
import datetime

# The above could be sent to an independent module
import backtrader as bt
import backtrader.feeds as btfeeds
import backtrader.indicators as btind
from backtrader.analyzers import (SQN, AnnualReturn, TimeReturn, SharpeRatio,
                                  TradeAnalyzer, DrawDown)
from backtrader.utils import AutoOrderedDict, AutoDict

class MarginAnalyzer(bt.Analyzer):
    def create_analysis(self):
        self.rets = AutoOrderedDict()

    def stop(self):
        super(MarginAnalyzer, self).stop()
        self.rets._close()

    def notify_order(self, order):
        if order.status == order.Margin:
            self.rets.status = order.getstatusname()
            self.rets.datetime =  datetime.datetime.fromtimestamp(order.created.dt).strftime('%Y-%m-%d %H:%M:%S')
            self.rets.size = order.created.size

class IndicatorAnalyzer(bt.Analyzer):
    def create_analysis(self):
        self.rets = AutoOrderedDict()
        self.rets.total.total = 0
        self.max_scaled_ewmac1_forcast = 0.0
        self.min_scaled_ewmac1_forcast = 0.0
        self.max_scaled_ewmac2_forcast = 0.0
        self.min_scaled_ewmac2_forcast = 0.0
        self.max_scaled_combined_forcast = 0.0
        self.min_scaled_combined_forcast = 0.0
        self.max_target_percent = 0.0

    def stop(self):
        super(IndicatorAnalyzer, self).stop()
        self.rets._close()

    def next(self):
        self.rets[self.data.datetime.datetime()].sigma_p = self.strategy.sigma_p[0]
        self.rets[self.data.datetime.datetime()].sigma_t = self.strategy.sigma_t[0]
        self.rets[self.data.datetime.datetime()].scaled_ewmac1_forcast = self.strategy.scaled_ewmac1_forcast[0]
        self.rets[self.data.datetime.datetime()].scaled_ewmac2_forcast = self.strategy.scaled_ewmac2_forcast[0]

        if self.strategy.scaled_ewmac1_forcast[0] > self.max_scaled_ewmac1_forcast:
            self.max_scaled_ewmac1_forcast = self.strategy.scaled_ewmac1_forcast[0]

        if self.strategy.scaled_ewmac2_forcast[0] > self.max_scaled_ewmac2_forcast:
            self.max_scaled_ewmac2_forcast = self.strategy.scaled_ewmac2_forcast[0]

        if self.strategy.scaled_ewmac1_forcast[0] < self.min_scaled_ewmac1_forcast:
            self.min_scaled_ewmac1_forcast = self.strategy.scaled_ewmac1_forcast[0]

        if self.strategy.scaled_ewmac2_forcast[0] < self.min_scaled_ewmac2_forcast:
            self.min_scaled_ewmac2_forcast = self.strategy.scaled_ewmac2_forcast[0]

        self.rets[self.data.datetime.datetime()].max_scaled_ewmac1_forcast = self.max_scaled_ewmac1_forcast
        self.rets[self.data.datetime.datetime()].max_scaled_ewmac2_forcast = self.max_scaled_ewmac2_forcast
        self.rets[self.data.datetime.datetime()].min_scaled_ewmac1_forcast = self.min_scaled_ewmac1_forcast
        self.rets[self.data.datetime.datetime()].min_scaled_ewmac2_forcast = self.min_scaled_ewmac2_forcast


        if self.max_scaled_combined_forcast < self.strategy.scaled_combined_forcast[0]:
            self.max_scaled_combined_forcast = self.strategy.scaled_combined_forcast[0]

        if self.min_scaled_combined_forcast > self.strategy.scaled_combined_forcast[0]:
            self.min_scaled_combined_forcast = self.strategy.scaled_combined_forcast[0]

        self.rets[self.data.datetime.datetime()].max_scaled_combined_forcast = self.max_scaled_combined_forcast
        self.rets[self.data.datetime.datetime()].min_scaled_combined_forcast = self.min_scaled_combined_forcast
        self.rets[self.data.datetime.datetime()].capital = self.strategy.capital
        self.rets[self.data.datetime.datetime()].target_size = self.strategy.target_size
        self.rets[self.data.datetime.datetime()].target_percent = self.strategy.target_percent
        self.rets[self.data.datetime.datetime()].buffer_n = self.strategy.buffer_n

        if self.strategy.target_percent > self.max_target_percent:
            self.max_target_percent = self.strategy.target_percent

        self.rets[self.data.datetime.datetime()].max_target_percent = self.max_target_percent



class MultiTrendStrategyTwoGroups(bt.Strategy):
    params = dict(
        sigma_period=82,
        annal_scale=16,
        fdm_scale=1.09,
        target_risk=0.3, #have great impact on return
        buffer_n=0.3,
        ewmac1=2,
        ewmac2=7,
        ewmac1_forcast_scalar = 3.9,
        ewmac2__forcast_scalar=3.59,
        cap_max=15,
        cap_min=-11
    )

    # EWMAC2 EWMAC4 EWMAC8 EWMAC16 EWMAC32 EWMAC64
    forcast_scalar = [12.1, 8.53, 5.95, 4.10, 2.79, 1.91]

    def log(self, txt, dt=None):
        dt = dt or self.data.datetime[0]
        dt = bt.num2date(dt)
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        self.daily_return = self.data.close(0) - self.data.close(-1)
        self.sigma_p = btind.StandardDeviation(self.daily_return, movav=btind.MovAv.EMA, period=self.p.sigma_period)
        self.daily_return_pct = bt.DivByZero(self.daily_return, self.data.close(-1))
        self.sigma_t_daily = btind.StandardDeviation(self.daily_return_pct, movav=btind.MovAv.EMA, period=self.p.sigma_period)
        self.sigma_t = self.sigma_t_daily * self.p.annal_scale
        self.ewma1_fast = btind.MovAv.EMA(self.data.close, period=self.p.ewmac1)
        self.ewma1_slow = btind.MovAv.EMA(self.data.close, period=self.p.ewmac1 * 4)
        self.raw_ewmac1_forcast = (self.ewma1_fast - self.ewma1_slow) / self.sigma_p
        self.scaled_ewmac1_forcast = self.raw_ewmac1_forcast * self.p.ewmac1_forcast_scalar
        self.avg_scaled_ewmac1_forcast = btind.MovAv.SMA(self.scaled_ewmac1_forcast, period=32)
        self.capped_ewmac1_forcast = bt.Max(bt.Min(self.scaled_ewmac1_forcast, self.p.cap_max), self.p.cap_min)

        self.ewma2_fast = btind.MovAv.EMA(self.data.close, period=self.p.ewmac2)
        self.ewma2_slow = btind.MovAv.EMA(self.data.close, period=self.p.ewmac2 * 4)
        self.raw_ewmac2_forcast = (self.ewma2_fast - self.ewma2_slow) / self.sigma_p
        self.scaled_ewmac2_forcast = self.raw_ewmac2_forcast * self.p.ewmac2__forcast_scalar
        self.avg_scaled_ewmac2_forcast = btind.MovAv.SMA(self.scaled_ewmac2_forcast, period=32)
        self.capped_ewmac2_forcast = bt.Max(bt.Min(self.scaled_ewmac2_forcast, self.p.cap_max), self.p.cap_min)

        self.raw_combined_forcast = (self.capped_ewmac1_forcast + self.capped_ewmac2_forcast) / 2.0
        self.scaled_combined_forcast = self.raw_combined_forcast * self.p.fdm_scale
        self.capped_combined_forcast = bt.Max(bt.Min(self.scaled_combined_forcast, self.p.cap_max), self.p.cap_min)
        self.capital = 0.0
        self.target_size = 0.0
        self.target_percent = 0.0
        self.buffer_n = 0.0

    def next(self):
        self.capital = self.broker.getvalue()
        self.target_size = (self.capital * self.capped_combined_forcast[0] * self.p.target_risk) / \
                      (10 * self.data.close[0] * self.sigma_t[0])
        self.target_percent = (self.capped_combined_forcast[0] * self.p.target_risk) / \
                              (10  * self.sigma_t[0]) * 100.0

        self.buffer_n = self.p.buffer_n * (self.capital * self.p.target_risk) / (self.data.close[0] * self.sigma_t[0])

        position = self.broker.getposition(self.data)

        if not position.size and self.target_size != 0:
            self.order_target_size(target=self.target_size)
        else:
            if abs(self.target_size - position.size) > self.buffer_n:
                self.order_target_size(target=self.target_size)



def runstrategy():
    args = parse_args()
    cerebro = bt.Cerebro()

    fromdate = datetime.datetime.strptime(args.fromdate, '%Y-%m-%d')
    todate = datetime.datetime.strptime(args.todate, '%Y-%m-%d')

    # Create the 1st data
    data = btfeeds.GenericCSVData(
        dataname=args.data,
        fromdate=fromdate,
        todate=todate,
        dtformat=('%Y-%m-%d %H:%M:%S'),
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        timeframe=bt.TimeFrame.Minutes
    )

    cerebro.adddata(data)
    cerebro.addstrategy(MultiTrendStrategyTwoGroups)
    cerebro.broker.setcash(10000)

    cerebro.broker.setcommission(commission=0.0005,
                                 commtype=bt.CommInfoBase.COMM_PERC,
                                 stocklike=True,
                                 leverage=10)

    cerebro.broker.set_slippage_perc(perc=0.00001)

    cerebro.addanalyzer(SQN, _name="sqn")
    cerebro.addanalyzer(TradeAnalyzer, _name="trade")
    cerebro.addanalyzer(DrawDown, _name="drawdown")
    #cerebro.addanalyzer(IndicatorAnalyzer, _name="indicator")
    cerebro.addanalyzer(AnnualReturn, _name="annual")
    cerebro.addanalyzer(MarginAnalyzer, _name="margin")

    cerebro.addwriter(bt.WriterFile, out="D:\\open_source\\backtrader\\samples\\crypto\\multi_trend.log")

    result = cerebro.run()
    sqn = result[0].analyzers.sqn.get_analysis()

    print("value {}".format(cerebro.broker.getvalue()))

    print("sqn {}".format(sqn))

    trade = result[0].analyzers.trade.get_analysis()
    print("trade {}".format(trade))

    drawdown = result[0].analyzers.drawdown.get_analysis()
    print("drawdown {}".format(drawdown))

    annual = result[0].analyzers.annual.get_analysis()
    print("annual {}".format(annual))

    margin = result[0].analyzers.margin.get_analysis()
    print("margin {}".format(margin))

    return sqn



def parse_args():
    parser = argparse.ArgumentParser(description='TimeReturn')

    parser.add_argument('--data', '-d',
                        default='D:\\open_source\\backtrader\\datas'
                                '\\binance\\data\\spot\\final\\klines'
                                '\\BTCUSDT\\4h\\BTCUSDT-4h.csv',
                        help='data to add to the system')

    parser.add_argument('--fromdate', '-f',
                        default='2020-01-01',
                        help='Starting date in YYYY-MM-DD format')

    parser.add_argument('--todate', '-t',
                        default='2024-12-31',
                        help='Starting date in YYYY-MM-DD format')

    return parser.parse_args()


if __name__ == '__main__':
    runstrategy()
