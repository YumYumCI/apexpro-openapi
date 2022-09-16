import base64
import decimal
import hashlib
import hmac
import math

from apexpro.http_public import HttpPublic
from web3 import Web3

from apexpro import HTTP, private_key_to_public_key_pair_hex
from apexpro.constants import URL_SUFFIX, OFF_CHAIN_KEY_DERIVATION_ACTION, OFF_CHAIN_ONBOARDING_ACTION, ORDER_SIDE_BUY
from apexpro.helpers.request_helpers import generate_query_path, \
    generate_now, random_client_id, iso_to_epoch_seconds, epoch_seconds_to_iso
from apexpro.starkex.constants import ONE_HOUR_IN_SECONDS, ORDER_SIGNATURE_EXPIRATION_BUFFER_HOURS
from apexpro.starkex.order import SignableOrder, DECIMAL_CONTEXT_ROUND_UP, DECIMAL_CONTEXT_ROUND_DOWN


class HttpPrivate(HttpPublic):
    def _private_request(
            self,
            method,
            path,
            data={},
            headers=None
    ):
        now_iso = generate_now()
        if self.api_key_credentials is not None:
            signature = self.sign(
                request_path=path,
                method=method.upper(),
                iso_timestamp=str(now_iso),
                data=data,
            )
            headers = {
                'APEX-SIGNATURE': signature,
                'APEX-API-KEY': self.api_key_credentials['key'],
                'APEX-TIMESTAMP': str(now_iso),
                'APEX-PASSPHRASE': self.api_key_credentials['passphrase'],
            }
        return self._submit_request(
            method=method,
            path=self.endpoint + path,
            headers=headers,
            query=data,
        )

    def _get(self, endpoint, params):
        return self._private_request(
            'GET',
            generate_query_path(endpoint, params),
        )

    def _post(self, endpoint, data, headers=None):
        return self._private_request(
            'POST',
            endpoint,
            data,
            headers
        )

    # ============ Signing ============

    def sign(
            self,
            request_path,
            method,
            iso_timestamp,
            data,
    ):
        sortedItems=sorted(data.items(),key=lambda x:x[0],reverse=False)
        dataString = '&'.join('{key}={value}'.format(
            key=x[0], value=x[1]) for x in sortedItems if x[1] is not None)

        message_string = (
                iso_timestamp +
                method +
                request_path +
                dataString
        )

        hashed = hmac.new(
            base64.standard_b64encode(
                (self.api_key_credentials['secret']).encode(encoding='utf-8'),
            ),
            msg=message_string.encode(encoding='utf-8'),
            digestmod=hashlib.sha256,
        )
        return base64.standard_b64encode(hashed.digest()).decode()

    def generate_nonce(self, **kwargs):
        """"
        POST: Generate nonce.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-post-generate-nonce
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/generate-nonce"
        return self._private_request(
            method="POST",
            path=path,
            data=kwargs
        )

    def register_user(
            self,
            nonce,
            starkKey=None,
            stark_public_key_y_coordinate=None,
            ethereum_address=None,
            referred_by_affiliate_link=None,
            country=None,
            isLpAccount=None,
            eth_mul_address=None,
    ):
        """"
        POST Registration & Onboarding.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-post-registration-amp-onboarding
        :returns: Request results as dictionary.
        """
        stark_key = starkKey or self.stark_public_key
        stark_key_y = (
                stark_public_key_y_coordinate or self.stark_public_key_y_coordinate
        )
        if stark_key is None:
            raise ValueError(
                'STARK private key or public key is required'
            )
        if stark_key_y is None:
            raise ValueError(
                'STARK private key or public key y-coordinate is required'
            )

        eth_address = ethereum_address or self.default_address
#0x6f4ae7978b936f91360d70eed28b54280a75cf54a44d029ddd604d1260bd82906a5b0f705785c7394776026fd2bd74b8c956cc7648982f0aea1bb86ed11c8d6b1c00
        signature = self.signer.sign(
            eth_address,
            action=OFF_CHAIN_ONBOARDING_ACTION,
            nonce=nonce,
        )

        path = URL_SUFFIX + "/v1/onboarding"
        onboardingRes = self._private_request(
            method="POST",
            path=path,
            data= {
                'starkKey': stark_key,
                'starkKeyYCoordinate': stark_key_y,
                'referredByAffiliateLink': referred_by_affiliate_link,
                'ethereumAddress': eth_address,
                'country': country,
                'category': 'CATEGORY_API',
                'isLpAccount': isLpAccount,
                'ethMulAddress': eth_mul_address,
            },
            headers={
                'APEX-SIGNATURE': signature,
                'APEX-ETHEREUM-ADDRESS': eth_address,
            }
        )
        if onboardingRes.get('data') is not None:
            self.user = onboardingRes['data']['user']
            self.account = onboardingRes['data']['account']
        return onboardingRes

    def derive_stark_key(
            self,
            ethereum_address=None,
    ):
        signature = self.starkeySigner.sign_message(
            ethereum_address or self.default_address,
            action=OFF_CHAIN_KEY_DERIVATION_ACTION,
            )
        signature_int = int(signature, 16)
        hashed_signature = Web3.solidityKeccak(['uint256'], [signature_int])
        private_key_int = int(hashed_signature.hex(), 16) >> 5
        private_key_hex = hex(private_key_int)
        public_x, public_y = private_key_to_public_key_pair_hex(
            private_key_hex,
        )
        return {
            'public_key': public_x,
            'public_key_y_coordinate': public_y,
            'private_key': private_key_hex
        }

    def user(self, **kwargs):
        """"
        GET Retrieve User Data.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-user-data
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/user"
        userRes = self._get(
            endpoint=path,
            params=kwargs
        )
        self.user = userRes['data']
        return userRes

    def modify_user(self, **kwargs):
        """"
        POST Edit User Data.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-post-edit-user-data
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/modify-user"

        return self._post(
            endpoint=path,
            data=kwargs
        )

    def account(self, **kwargs):
        """"
        GET Retrieve User Account Data.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-user-account-data
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/account"
        accountRes =  self._get(
            endpoint=path,
            params=kwargs
        )
        self.account = accountRes['data']
        return accountRes
    def transfers(self, **kwargs):
        """"
        GET Retrieve User Deposit Data.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-user-deposit-data
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/transfers"
        return self._get(
            endpoint=path,
            params=kwargs
        )

    def withdraw_list(self, **kwargs):
        """"
        GET Retrieve User Withdrawal List.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-user-withdrawal-list
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/withdraw-list"
        return self._get(
            endpoint=path,
            params=kwargs
        )

    def uncommon_withdraw_fee(self, **kwargs):
        """"
        GET Fast & Cross-Chain Withdrawal Fees.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-fast-amp-cross-chain-withdrawal-fees
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/uncommon-withdraw-fee"
        return self._get(
            endpoint=path,
            params=kwargs
        )

    def transfer_limit(self, **kwargs):
        """"
        GET Retrieve Withdrawal & Transfer Limits.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-withdrawal-amp-transfer-limits
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/transfer-limit"
        return self._get(
            endpoint=path,
            params=kwargs
        )

    def fills(self, **kwargs):
        """"
        GET Retrieve Trade History.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-trade-history
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/fills"
        return self._get(
            endpoint=path,
            params=kwargs
        )

    def delete_order(self, **kwargs):
        """"
        POST Cancel Order.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-post-cancel-order
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/delete-order"
        return self._post(
            endpoint=path,
            data=kwargs
        )
    def delete_open_orders(self, **kwargs):
        """"
        POST Cancel all Open Orders
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-post-cancel-all-open-orders
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/delete-open-orders"
        return self._post(
            endpoint=path,
            data=kwargs
        )
    def open_orders(self, **kwargs):
        """"
        GET Retrieve Open Orders.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-open-orders
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/open-orders"
        return self._get(
            endpoint=path,
            params=kwargs
        )

    def history_orders(self, **kwargs):
        """"
        GET Retrieve All Order History.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-all-order-history
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/history-orders"
        return self._get(
            endpoint=path,
            params=kwargs
        )

    def get_order(self, **kwargs):
        """"
        GET Retrieve Order ID.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-order-id
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/get-order"
        return self._get(
            endpoint=path,
            params=kwargs
        )

    def funding(self, **kwargs):
        """"
        GET Retrieve Funding Rate.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-funding-rate
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/funding"
        return self._get(
            endpoint=path,
            params=kwargs
        )

    def notify_list(self, **kwargs):
        """"
        GET Retrieve Notification List.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-notification-list
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/notify-list"
        return self._get(
            endpoint=path,
            params=kwargs
        )

    def mark_notify_read(self, **kwargs):
        """"
        POST Mark Notification As Read.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-post-mark-notification-as-read
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/mark-notify-read"
        return self._post(
            endpoint=path,
            data=kwargs
        )

    def historical_pnl(self, **kwargs):
        """"
        GET Retrieve User Historial Profit and Loss.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-user-historial-profit-and-loss
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/historical-pnl"
        return self._get(
            endpoint=path,
            params=kwargs
        )

    def yesterday_pnl(self, **kwargs):
        """"
        GET Retrieve Yesterday's Profit & Loss.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-yesterday-39-s-profit-amp-loss
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/yesterday-pnl"
        return self._get(
            endpoint=path,
            params=kwargs
        )

    def history_value(self, **kwargs):
        """"
        GET Retrieve Historical Asset Value.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-historical-asset-value
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/history-value"
        return self._get(
            endpoint=path,
            params=kwargs
        )

    def mark_all_notify_read(self, **kwargs):
        """"
        POST Mark All Notifications As Read.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-post-mark-all-notifications-as-read
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/mark-all-notify-read"
        return self._post(
            endpoint=path,
            data=kwargs
        )

    def mark_all_notify_read(self, **kwargs):
        """"
        POST Mark All Notifications As Read.
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-post-mark-all-notifications-as-read
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/mark-all-notify-read"
        return self._post(
            endpoint=path,
            data=kwargs
        )

    def get_worst_price(self, **kwargs):
        """"
        get market price from orderbook
        :param kwargs: See
        https://api-docs.pro.apex.exchange/#privateapi-get-retrieve-worst-price
        :returns: Request results as dictionary.
        """

        path = URL_SUFFIX + "/v1/get-worst-price"
        return self._get(
            endpoint=path,
            params=kwargs
        )

