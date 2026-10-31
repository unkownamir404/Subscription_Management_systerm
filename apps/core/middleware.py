"""
Performance and Timing Middleware for Brightloop Subscription Management System.
Measures total request processing time and database queries, logging the metrics
and injecting a standard Server-Timing header for live latency observability.
"""
import time
import logging
from django.db import connection

logger = logging.getLogger("brightloop.performance")


class PerformanceTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_queries = len(connection.queries)
        start_time = time.perf_counter()

        response = self.get_response(request)

        duration = (time.perf_counter() - start_time) * 1000.0  # Duration in milliseconds
        query_count = len(connection.queries) - start_queries

        # Calculate DB execution time if connection.queries holds timing info
        db_time = 0.0
        if connection.queries and query_count > 0:
            for q in connection.queries[start_queries:]:
                try:
                    db_time += float(q.get("time", 0.0)) * 1000.0
                except (ValueError, TypeError):
                    pass

        # Set standard W3C Server-Timing header
        response["Server-Timing"] = (
            f'app;dur={duration:.2f}, '
            f'db;dur={db_time:.2f};desc="{query_count} queries"'
        )

        logger.info(
            f"Path: {request.path} | Duration: {duration:.2f}ms | Queries: {query_count}"
        )

        return response
