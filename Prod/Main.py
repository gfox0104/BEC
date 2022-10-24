# %%
import os
import re
from turtle import left
from xml.dom import ValidationErr
import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException
from binance import BinanceSocketManager
from binance.helpers import round_step_size
import requests
from datetime import datetime
import time
import sys
import math
import numpy as np
import dataframe_image as dfi


# %%
# environment variables
try:
    # Binance
    api_key = os.environ.get('binance_api')
    api_secret = os.environ.get('binance_secret')
    
    # Telegram
    telegramToken = os.environ.get('telegramToken') 
    telegram_chat_id = os.environ.get('telegram_chat_id')
except KeyError: 
    print("Environment variable does not exist")

# Binance Client
client = Client(api_key, api_secret)

# %%
# constants

# positionscheck file example
# Currency,position,quantity
# BTCBUSD,0,0.0

# strategy
# gTimeframe = client.KLINE_INTERVAL_1HOUR # "1h"
gFastMA = int("8")
gSlowMA = int("34")
gTimeFrameNum = int("1")
gtimeframeTypeShort = "h" # hour, day
gtimeframeTypeLong = "hour" # hour, day
gStrategyName = str(gFastMA)+"/"+str(gSlowMA)+" CROSS"

# percentage of balance to open position for each trade - example 0.1 = 10%
tradepercentage = float("0.01") #0.2%
minPositionSize = float("15.0") # minimum position size in usd
# risk percentage per trade - example 0.01 = 1%
risk = float("0.01")

# Telegram
url = f"https://api.telegram.org/bot{telegramToken}/getUpdates"
# print(requests.get(url).json())

# emoji
eStart   = u'\U000025B6'
eStop    = u'\U000023F9'
eWarning = u'\U000026A0'
eEnterTrade = u'\U0001F91E' #crossfingers
eExitTrade  = u'\U0001F91E' #crossfingers
eTradeWithProfit = u'\U0001F44D' # thumbs up
eTradeWithLoss   = u'\U0001F44E' # thumbs down
eInformation = u'\U00002139'


# %%
def sendTelegramMessage(emoji, msg):
    if not emoji:
        lmsg = msg
    else:
        lmsg = emoji+" "+msg
    url = f"https://api.telegram.org/bot{telegramToken}/sendMessage?chat_id={telegram_chat_id}&text={lmsg}"
    requests.get(url).json() # this sends the message

def sendTelegramAlert(emoji, date, coin, timeframe, strategy, ordertype, value, amount):
    lmsg = emoji + " " + str(date) + " - " + coin + " - " + strategy + " - " + timeframe + " - " + ordertype + " - " + "Value: " + str(value) + " - " + "Amount: " + str(amount)
    url = f"https://api.telegram.org/bot{telegramToken}/sendMessage?chat_id={telegram_chat_id}&text={lmsg}"
    requests.get(url).json() # this sends the message

def sendTelegramPhoto(photoName='balance.png'):
    # get current dir
    cwd = os.getcwd()
    limg = cwd+"/"+photoName
    # print(limg)
    oimg = open(limg, 'rb')
    url = f"https://api.telegram.org/bot{telegramToken}/sendPhoto?chat_id={telegram_chat_id}"
    requests.post(url, files={'photo':oimg}) # this sends the message

# %%
# read positions csv
posframe = pd.read_csv('positioncheck')
# posframe

# Todo
# get top 10 relative to BTC or USD strongest coins and trade those.
# the coins must have liquidity- choose from the top50 or 100 max from the marketcap rank 
# Add them automatically to positioncheck.
# remove the coins that are not so strong = not in an uptrend. example below 4H/1D 200MA
# 

# read orders csv
# we just want the header, there is no need to get all the existing orders.
# at the end we will append the orders to the csv
# sendTelegramMessage("", "read orders csv")
dforders = pd.read_csv('orders', nrows=0)
# dforders

# %%
# Not working properly yet
def spot_balance():
        sum_btc = 0.0
        balances = client.get_account()
        for _balance in balances["balances"]:
            asset = _balance["asset"]
            if True: #float(_balance["free"]) != 0.0 or float(_balance["locked"]) != 0.0:
                try:
                    btc_quantity = float(_balance["free"]) + float(_balance["locked"])
                    if asset == "BTC":
                        sum_btc += btc_quantity
                    else:
                        _price = client.get_symbol_ticker(symbol=asset + "BTC")
                        sum_btc += btc_quantity * float(_price["price"])
                except:
                    pass

        current_btc_price_USD = client.get_symbol_ticker(symbol="BTCUSDT")["price"]
        own_usd = sum_btc * float(current_btc_price_USD)
        print(" * Spot => %.8f BTC == " % sum_btc, end="")
        print("%.8f USDT" % own_usd)
# spot_balance()

# %%
def calcPositionSize():
    # sendTelegramMessage("", "calc position size")

    try:
        
        # get balance from BUSD
        stablecoin = client.get_asset_balance(asset='BUSD')
        stablecoin = float(stablecoin['free'])
        # print(stableBalance)

        # calculate position size based on the percentage per trade
        resultado = stablecoin*tradepercentage 
        resultado = round(resultado, 5)

        if resultado < minPositionSize:
            resultado = minPositionSize


        return resultado
    except BinanceAPIException as e:
        sendTelegramMessage(eWarning, e)
    
    

# %%
def getdata(coinPair):

    lstartDate = str(gSlowMA*gTimeFrameNum)+" "+gtimeframeTypeLong+" ago UTC" 
    ltimeframe = str(gTimeFrameNum)+gtimeframeTypeShort
    frame = pd.DataFrame(client.get_historical_klines(coinPair,
                                                    ltimeframe,
                                                    lstartDate))

    frame = frame[[0,4]]
    frame.columns = ['Time','Close']
    frame.Close = frame.Close.astype(float)
    frame.Time = pd.to_datetime(frame.Time, unit='ms')
    return frame

# %%
def applytechnicals(df):
    # df['FastSMA'] = df.Close.rolling(50).mean()
    # df['SlowSMA'] = df.Close.rolling(200).mean()
    
    df['FastMA'] = df['Close'].ewm(span=gFastMA, adjust=False).mean()
    df['SlowMA'] = df['Close'].ewm(span=gSlowMA, adjust=False).mean()


# %%
def changepos(curr, order, buy=True):
    # sendTelegramMessage("", "change pos")
    if buy:
        posframe.loc[posframe.Currency == curr, 'position'] = 1
        posframe.loc[posframe.Currency == curr, 'quantity'] = float(order['executedQty'])
    else:
        posframe.loc[posframe.Currency == curr, 'position'] = 0
        posframe.loc[posframe.Currency == curr, 'quantity'] = 0

    posframe.to_csv('positioncheck', index=False)


# %%
def adjustSize(coin, amount):

    # sendTelegramMessage("", "adjust size")
    
    for filt in client.get_symbol_info(coin)['filters']:
        if filt['filterType'] == 'LOT_SIZE':
            stepSize = float(filt['stepSize'])
            minQty = float(filt['minQty'])
            break

    order_quantity = round_step_size(amount, stepSize)
    return order_quantity


# %%
def trader():
    # sendTelegramMessage("", "trader")

    listPosition1 = posframe[posframe.position == 1].Currency
    listPosition0 = posframe[posframe.position == 0].Currency

    # check open positions and SELL if conditions are fulfilled 
    for coinPair in listPosition1:
        # sendTelegramMessage("",coinPair) 
        df = getdata(coinPair)
        applytechnicals(df)
        lastrow = df.iloc[-1]

        if lastrow.SlowMA > lastrow.FastMA:
            # sendTelegramMessage("",client.SIDE_SELL+" "+coinPair) 
            coinOnly = coinPair.replace('BUSD','')
            # was not selling because the buy order amount is <> from the balance => fees were applied and we get less than the buy order
            # thats why we need to get the current balance 
            # sendTelegramMessage("",client.SIDE_SELL+" coinOnly:"+coinOnly) 
            # balanceQty = client.get_asset_balance(asset=coinOnly)['free']
            try:
                balanceQty = float(client.get_asset_balance(asset=coinOnly)['free'])  
            except BinanceAPIException as ea:
                sendTelegramMessage(eWarning, ea)

            # sendTelegramMessage("",client.SIDE_SELL+" "+coinPair+" balanceQty:"+str(balanceQty))

            # print("balanceQty: ",balanceQty)
            buyOrderQty = float(posframe[posframe.Currency == coinPair].quantity.values[0])
            # sendTelegramMessage("",client.SIDE_SELL+" "+coinPair+" buyOrderQty:"+str(buyOrderQty))
            # print("buyOrderQty: ",buyOrderQty)
            sellQty = buyOrderQty
            # sendTelegramMessage("",client.SIDE_SELL+" "+coinPair+" sellQty: "+str(sellQty))
            if balanceQty < buyOrderQty:
                sellQty = balanceQty
                # sendTelegramMessage("",client.SIDE_SELL+" "+coinPair+" sellQty:"+str(sellQty))
            sellQty = adjustSize(coinPair, sellQty)
            sendTelegramMessage("",client.SIDE_SELL+" "+coinPair+" sellQty="+str(sellQty))
            if sellQty > 0: 
                
                try:        
                    order = client.create_order(symbol=coinPair,
                                            side=client.SIDE_SELL,
                                            type=client.ORDER_TYPE_MARKET,
                                            # quantity = posframe[posframe.Currency == coinPair].quantity.values[0]
                                            quantity = sellQty
                                            )
                    changepos(coinPair,order,buy=False)
                except BinanceAPIException as ea:
                    sendTelegramMessage(eWarning, ea)
                except BinanceOrderException as eo:
                    sendTelegramMessage(eWarning, eo)

                #add new row to end of DataFrame
                dforders.loc[len(dforders.index)] = [order['orderId'],coinPair, order['price'], order['executedQty'], order['side'], pd.to_datetime(order['transactTime'], unit='ms')]
                
                # print(order)
                # sendTelegramMessage(eExitTrade, order)
                sendTelegramAlert(eExitTrade,
                                # order['transactTime']
                                pd.to_datetime(order['transactTime'], unit='ms'), 
                                order['symbol'], 
                                str(gTimeFrameNum)+gtimeframeTypeShort, 
                                gStrategyName,
                                order['side'],
                                order['price'],
                                order['executedQty'])
            else:
                changepos(coinPair,'',buy=False)
        else:
            print(f'{coinPair} - Sell condition not fulfilled')
            sendTelegramMessage("",f'{coinPair} - Sell condition not fulfilled')

    # check coins not in positions and BUY if conditions are fulfilled
    for coinPair in listPosition0:
        # sendTelegramMessage("",coinPair) 
        df = getdata(coinPair)
        applytechnicals(df)
        lastrow = df.iloc[-1]
        if lastrow.FastMA > lastrow.SlowMA:
            positionSize = calcPositionSize()
            # sendTelegramMessage("", "calc position size 5")
            # print("positionSize: ", positionSize)
            sendTelegramMessage('',client.SIDE_BUY+" "+coinPair+" BuyQty="+str(positionSize))  
            if positionSize > 0:
                try:
                    order = client.create_order(symbol=coinPair,
                                                side=client.SIDE_BUY,
                                                type=client.ORDER_TYPE_MARKET,
                                                quoteOrderQty = positionSize) #positionSize 
                    changepos(coinPair,order,buy=True)
                except BinanceAPIException as ea:
                    sendTelegramMessage(eWarning, ea)
                except BinanceOrderException as eo:
                    sendTelegramMessage(eWarning, eo)
                
                #add new row to end of DataFrame
                dforders.loc[len(dforders.index)] = [order['orderId'],coinPair, order['price'], order['executedQty'], order['side'], pd.to_datetime(order['transactTime'], unit='ms')]
                        
                
                sendTelegramAlert(eEnterTrade,
                                # order['transactTime'], 
                                pd.to_datetime(order['transactTime'], unit='ms'),
                                order['symbol'], 
                                str(gTimeFrameNum)+gtimeframeTypeShort, 
                                gStrategyName,
                                order['side'],
                                order['price'],
                                order['executedQty'])
            else:
                sendTelegramMessage(eWarning,client.SIDE_BUY+" "+coinPair+" with qty = 0!")
                
        else:
            print(f'{coinPair} - Buy condition not fulfilled')
            sendTelegramMessage("",f'{coinPair} - Buy condition not fulfilled')

def custom_style(row):
    bold = 'bold' if row < 0 else ''

    # if row.values[-1] != "0.0":
    #     bold = 'bold'
    # else

    # return ['background-color: %s' % color]*len(row.values)
    return 'font-weight: bold'


def main():
    # inform that is running
    sendTelegramMessage(eStart,"Binance Trader Bot - Start")

    trader()

    # add orders to csv file
    if not dforders.empty: 
        dforders.to_csv('orders', mode='a', index=False, header=False)


    # posframe.drop('position', axis=1, inplace=True)
    # posframe.style.applymap(custom_style)
     
    # send balance
    print(posframe)

    sendTelegramMessage("",posframe.to_string())

    # dfi.export(posframe, 'balance.png', fontsize=8, table_conversion='matplotlib')
    # sendTelegramPhoto()

    # Todo
    # set orders filled buy value
    # get orders where price = 0 
    # get filled price
    # set price and save to csv file

    # inform that ended
    sendTelegramMessage(eStop, "Binance Trader Bot - End")

main()



