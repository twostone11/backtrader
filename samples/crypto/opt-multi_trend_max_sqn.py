from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import argparse
import datetime
import optuna

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

class MultiTrendStrategyTwoGroups(bt.Strategy):
    params = dict(
        sigma_period=72,
        annal_scale=16,
        fdm_scale=1.03,
        target_risk=0.2,
        buffer_n=0.17,
        ewmac1=4,
        ewmac2=8,
        ewmac1_forcast_scalar = 4.10,
        ewmac2__forcast_scalar=2.79,
        cap_max=20,
        cap_min=-20
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

def runstrategy(trial):
    sigma_period = trial.suggest_int('sigma_period', 30, 100, step=2)
    annal_scale = trial.suggest_int('annal_scale', 8, 32, step=2)
    fdm_scale = trial.suggest_float('fdm_scale', 1.0, 1.1, step=0.01)
    target_risk = trial.suggest_float('target_risk', 0.1, 0.3, step=0.01)
    buffer_n = trial.suggest_float('buffer_n', 0.05, 0.3, step=0.01)
    ewmac1 = trial.suggest_int('ewmac1', 2, 16, step=1)
    ewmac2 = trial.suggest_int('ewmac2', 4, 32, step=1)
    ewmac1_forcast_scalar = trial.suggest_float('ewmac1_forcast_scalar', 3.10, 5.10, step=0.1)
    ewmac2__forcast_scalar = trial.suggest_float('ewmac2__forcast_scalar', 1.79, 3.79, step=0.1)
    cap_max = trial.suggest_int('cap_max', 10, 30, step=1)
    cap_min = trial.suggest_int('cap_min', -13, -10, step=1)

    cerebro = bt.Cerebro()

    fromdate = datetime.datetime.strptime('2020-01-01', '%Y-%m-%d')
    todate = datetime.datetime.strptime('2024-12-31', '%Y-%m-%d')

    # Create the 1st data
    data = btfeeds.GenericCSVData(
        dataname='D:\\open_source\\backtrader\\datas'
                                '\\binance\\data\\spot\\final\\klines'
                                '\\BTCUSDT\\4h\\BTCUSDT-4h.csv',
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
    cerebro.addstrategy(MultiTrendStrategyTwoGroups,
                        sigma_period=sigma_period,
                        annal_scale=annal_scale,
                        fdm_scale=fdm_scale,
                        target_risk=target_risk,
                        buffer_n=buffer_n,
                        ewmac1=ewmac1,
                        ewmac2=ewmac2,
                        ewmac1_forcast_scalar=ewmac1_forcast_scalar,
                        ewmac2__forcast_scalar=ewmac2__forcast_scalar,
                        cap_max=cap_max,
                        cap_min=cap_min
                        )
    cerebro.broker.setcash(10000)

    cerebro.broker.setcommission(commission=0.0005,
                                 commtype=bt.CommInfoBase.COMM_PERC,
                                 stocklike=True,
                                 leverage=10)

    cerebro.broker.set_slippage_perc(perc=0.00001)

    cerebro.addanalyzer(SQN, _name="sqn")
    cerebro.addanalyzer(MarginAnalyzer, _name="margin")
    cerebro.addanalyzer(DrawDown, _name="drawdown")
    # cerebro.addanalyzer(AnnualReturn)

    # cerebro.addwriter(bt.WriterFile, out="D:\\open_source\\backtrader\\samples\\crypto\\multi_trend_{}".format(\
    #     datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')))

    result = cerebro.run()
    sqn = result[0].analyzers.sqn.get_analysis()
    print("sqn {}".format(sqn))

    margin = result[0].analyzers.margin.get_analysis()
    if margin:
        print("margin {}".format(margin))
        return 0.0

    drawdown = result[0].analyzers.drawdown.get_analysis()
    if drawdown.max.drawdown > 50.0:
        print("drawdown {}".format(drawdown))
        return 0.0

    return sqn.sqn

def run_opt():
    study = optuna.create_study(direction='maximize')
    study.optimize(runstrategy, n_trials=10000)
    print(study.best_params)
    print(study.best_value)


if __name__ == '__main__':
    run_opt()
