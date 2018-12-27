# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2017-2018 reverendus
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import urllib
from pprint import pformat
from typing import List

import requests
import hmac
import base64
import datetime

from pyexchange.model import Candle
from pymaker.numeric import Wad
from pymaker.util import http_response_summary


class Order:
    def __init__(self, order_id: int, timestamp: int, pair: str,
                 is_sell: bool, price: Wad, amount: Wad, deal_amount: Wad):
        assert(isinstance(order_id, int))
        assert(isinstance(timestamp, int))
        assert(isinstance(pair, str))
        assert(isinstance(is_sell, bool))
        assert(isinstance(price, Wad))
        assert(isinstance(amount, Wad))
        assert(isinstance(deal_amount, Wad))

        self.order_id = order_id
        self.timestamp = timestamp
        self.pair = pair
        self.is_sell = is_sell
        self.price = price
        self.amount = amount
        self.deal_amount = deal_amount

    @property
    def sell_to_buy_price(self) -> Wad:
        return self.price

    @property
    def buy_to_sell_price(self) -> Wad:
        return self.price

    @property
    def remaining_buy_amount(self) -> Wad:
        return (self.amount - self.deal_amount)*self.price if self.is_sell else (self.amount - self.deal_amount)

    @property
    def remaining_sell_amount(self) -> Wad:
        return (self.amount - self.deal_amount) if self.is_sell else (self.amount - self.deal_amount)*self.price

    def __eq__(self, other):
        assert(isinstance(other, Order))

        return self.order_id == other.order_id and \
               self.pair == other.pair

    def __hash__(self):
        return hash((self.order_id, self.pair))

    def __repr__(self):
        return pformat(vars(self))


class Trade:
    def __init__(self,
                 trade_id: id,
                 timestamp: int,
                 is_sell: bool,
                 price: Wad,
                 amount: Wad,
                 amount_symbol: str):
        assert(isinstance(trade_id, int))
        assert(isinstance(timestamp, int))
        assert(isinstance(is_sell, bool))
        assert(isinstance(price, Wad))
        assert(isinstance(amount, Wad))
        assert(isinstance(amount_symbol, str))

        self.trade_id = trade_id
        self.timestamp = timestamp
        self.is_sell = is_sell
        self.price = price
        self.amount = amount
        self.amount_symbol = amount_symbol

    def __eq__(self, other):
        assert(isinstance(other, Trade))
        return self.trade_id == other.trade_id and \
               self.timestamp == other.timestamp and \
               self.is_sell == other.is_sell and \
               self.price == other.price and \
               self.amount == other.amount and \
               self.amount_symbol == other.amount_symbol

    def __hash__(self):
        return hash((self.trade_id,
                     self.timestamp,
                     self.is_sell,
                     self.price,
                     self.amount,
                     self.amount_symbol))

    def __repr__(self):
        return pformat(vars(self))


class OKEXApi:
    """OKEX API V3
    """

    logger = logging.getLogger()

    def __init__(self, api_server: str, api_key: str, secret_key: str, passphrase: str, timeout: float):
        assert(isinstance(api_server, str))
        assert(isinstance(api_key, str))
        assert(isinstance(secret_key, str))
        assert(isinstance(passphrase, str))
        assert(isinstance(timeout, float))

        self.api_server = api_server
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.timeout = timeout

    def ticker(self, pair: str):
        assert(isinstance(pair, str))
        return self._http_get(f"/api/spot/v3/instruments/{pair}ticker")

    def depth(self, pair: str):
        assert(isinstance(pair, str))
        return self._http_get(f"/api/spot/v3/instruments/{pair}/book")

    def get_balances(self) -> list:
        """
        [{"currency": “BTC”,
        “balance”: ”2.3”,
        “hold”: “2”,
        "available": “0.3”,
        “id”:”344555”
        }]
        :return:
        """
        return self._http_get("/api/spot/v3/accounts")

    def get_orders(self, pair: str) -> List[Order]:
        """获取active订单"""
        assert(isinstance(pair, str))

        result = self._http_get("/api/spot/v3/orders_pending", f'instrument_id={pair}')

        orders = filter(self._filter_order, result)
        return list(map(self._parse_order, orders))

    def place_order(self, pair: str, is_sell: bool, price: Wad, amount: Wad) -> int:
        assert(isinstance(pair, str))
        assert(isinstance(is_sell, bool))
        assert(isinstance(price, Wad))
        assert(isinstance(amount, Wad))

        self.logger.info(f"Placing order ({'SELL' if is_sell else 'BUY'}, amount {amount} of {pair},"
                         f" price {price})...")

        result = self._http_post("/api/spot/v3/orders", {
            'instrument_id': pair,
            'side': 'sell' if is_sell else 'buy',
            'type': 'limit',
            'price': str(price),
            'size': str(amount)
        })
        order_id = int(result['order_id'])
        bol_result = int(result['result'])

        self.logger.info(f"Placed order ({'SELL' if is_sell else 'BUY'}, amount {amount} of {pair},"
                         f" price {price}) as #{order_id}, result {bol_result}")

        return order_id

    def cancel_order(self, pair: str, order_id: int) -> bool:
        assert(isinstance(pair, str))
        assert(isinstance(order_id, int))

        self.logger.info(f"Cancelling order #{order_id}...")

        result = self._http_post(f"/api/spot/v3/cancel_orders/{order_id}", {
            'instrument_id': pair
        })
        success = int(result['order_id']) == order_id

        if success:
            self.logger.info(f"Cancelled order #{order_id}")
        else:
            self.logger.info(f"Failed to cancel order #{order_id}")

        return success

    def get_trades(self, pair: str, page_number: int = 1):
        assert(isinstance(pair, str))
        assert(isinstance(page_number, int))
        raise Exception("get_trades() not available for OKEX")

    def get_all_trades(self, pair: str, page_number: int = 1) -> List[Trade]:
        assert(isinstance(pair, str))
        assert(isinstance(page_number, int))
        raise Exception("get_trades() not available for OKEX")

    @staticmethod
    def _filter_order(item: dict) -> bool:
        assert(isinstance(item, dict))
        return item['type'] in ['buy', 'sell']

    @staticmethod
    def _parse_order(item: dict) -> Order:
        assert(isinstance(item, dict))
        return Order(order_id=item['order_id'],
                     timestamp=int(item['create_date']/1000),
                     pair=item['symbol'],
                     is_sell=item['type'] == 'sell',
                     price=Wad.from_number(item['price']),
                     amount=Wad.from_number(item['amount']),
                     deal_amount=Wad.from_number(item['deal_amount']))

    def _create_signature(self, timestamp, method, request_path, body, secret_key):
        if str(body) == '{}' or str(body) == 'None':
            body = ''
        message = str(timestamp) + str.upper(method) + request_path + str(body)
        mac = hmac.new(bytes(secret_key, encoding='utf8'), bytes(message, encoding='utf-8'), digestmod='sha256')
        d = mac.digest()
        return base64.b64encode(d)

    @staticmethod
    def _result(result, check_result: bool) -> dict:
        assert(isinstance(check_result, bool))

        if not result.ok:
            raise Exception(f"OKCoin API invalid HTTP response: {http_response_summary(result)}")

        try:
            data = result.json()
        except Exception:
            raise Exception(f"OKCoin API invalid JSON response: {http_response_summary(result)}")

        if check_result:
            if 'error_code' in data:
                raise Exception(f"OKCoin API negative response: {http_response_summary(result)}")

        return data

    def _get_timestamp(self):
        now = datetime.datetime.now()
        t = now.isoformat()
        return t + "Z"

    def _get_server_timestamp(self):
        data = self._result(requests.get(f'{self.api_server}/api/general/v3/time'), False)
        return data['iso']

    def _okex_header(self, method, request_path, body=""):

        # timestamp = self._get_timestamp()
        timestamp = self._get_server_timestamp()
        """
        OK-ACCESS-SIGN的请求头是对timestamp + method + requestPath + body字符串(+表示字符串连接)，以及secretKey，使用HMAC SHA256方法加密，通过BASE64编码输出而得到的。
        """
        message = str(timestamp) + str.upper(method) + request_path + body
        mac = hmac.new(bytes(self.secret_key, encoding='utf8'), bytes(message, encoding='utf-8'), digestmod='sha256')
        d = mac.digest()
        sign = base64.b64encode(d)

        logging.debug(f'message {message}')

        header = dict()
        header['Content-Type'] = "application/json"
        header['OK-ACCESS-KEY'] = self.api_key
        header['OK-ACCESS-SIGN'] = sign
        header['OK-ACCESS-TIMESTAMP'] = str(timestamp)
        header['OK-ACCESS-PASSPHRASE'] = self.passphrase
        return header

    def _http_get(self, resource: str, params: str = '', check_result: bool = True):
        assert(isinstance(resource, str))
        assert(isinstance(params, str))
        assert(isinstance(check_result, bool))

        if params != '':
            resource = f"{resource}?{params}"

        url = f"{self.api_server}{resource}"

        okex_header = self._okex_header('GET', resource)

        return self._result(requests.get(url=url,
                                         headers=okex_header,
                                         timeout=self.timeout), check_result)

    def _http_post(self, resource: str, params: dict):
        assert(isinstance(resource, str))
        assert(isinstance(params, dict))

        return self._result(requests.post(url=f"{self.api_server}{resource}",
                                          data=urllib.parse.urlencode(params),
                                          headers=self._okex_header('POST', resource, str(params)),
                                          timeout=self.timeout), True)