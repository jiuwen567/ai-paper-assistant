from rest_framework.pagination import PageNumberPagination


def validated(serializer_class, request, **kwargs):
    serializer = serializer_class(data=request.data, **kwargs)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def paginated(queryset, serializer_class, request):
    pagination = PageNumberPagination()
    pagination.page_size = 20
    page = pagination.paginate_queryset(queryset, request)
    return pagination.get_paginated_response(
        serializer_class(page, many=True, context={"request": request}).data
    )
