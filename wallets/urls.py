from django.urls import path

from wallets.views import (
    CustomerCreateView,
    WalletBalanceView,
    WalletDepositView,
    WalletTransactionsView,
    WalletTransferView,
    WalletWithdrawView,
)

app_name = "wallets"

urlpatterns = [
    path("customers/", CustomerCreateView.as_view(), name="customer-create"),
    path("wallets/transfer/", WalletTransferView.as_view(), name="wallet-transfer"),
    path("wallets/<uuid:wallet_id>/deposit/", WalletDepositView.as_view(), name="wallet-deposit"),
    path("wallets/<uuid:wallet_id>/withdraw/", WalletWithdrawView.as_view(), name="wallet-withdraw"),
    path("wallets/<uuid:wallet_id>/balance/", WalletBalanceView.as_view(), name="wallet-balance"),
    path("wallets/<uuid:wallet_id>/transactions/", WalletTransactionsView.as_view(), name="wallet-transactions"),
]
