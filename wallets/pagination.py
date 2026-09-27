from rest_framework.pagination import CursorPagination


class TransactionCursorPagination(CursorPagination):
    ordering = "-created_at"
    page_size = 20
