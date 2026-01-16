#!/usr/bin/env python3
"""
Splunk MCP Server

A Model Context Protocol server for interacting with Splunk.
Provides tools for searching, managing indexes, and retrieving data from Splunk.
"""

import os
import re
import csv
import json
from typing import Any, Optional
from datetime import datetime

import splunklib.client as client
import splunklib.results as results
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("Splunk MCP Server")

# Splunk connection configuration
SPLUNK_HOST = os.getenv("SPLUNK_HOST", "localhost")
SPLUNK_PORT = int(os.getenv("SPLUNK_PORT", "8089"))
SPLUNK_USERNAME = os.getenv("SPLUNK_USERNAME")
SPLUNK_PASSWORD = os.getenv("SPLUNK_PASSWORD")
SPLUNK_TOKEN = os.getenv("SPLUNK_TOKEN")
SPLUNK_SCHEME = os.getenv("SPLUNK_SCHEME", "https")


def get_splunk_service() -> client.Service:
    """
    Create and return a Splunk service connection.

    Uses token authentication if SPLUNK_TOKEN is set, otherwise uses username/password.
    """
    try:
        if SPLUNK_TOKEN:
            service = client.connect(
                host=SPLUNK_HOST,
                port=SPLUNK_PORT,
                scheme=SPLUNK_SCHEME,
                splunkToken=SPLUNK_TOKEN,
                autologin=True
            )
        elif SPLUNK_USERNAME and SPLUNK_PASSWORD:
            service = client.connect(
                host=SPLUNK_HOST,
                port=SPLUNK_PORT,
                scheme=SPLUNK_SCHEME,
                username=SPLUNK_USERNAME,
                password=SPLUNK_PASSWORD,
                autologin=True
            )
        else:
            raise ValueError(
                "Splunk credentials not configured. Set SPLUNK_TOKEN or "
                "SPLUNK_USERNAME and SPLUNK_PASSWORD environment variables."
            )
        return service
    except Exception as e:
        raise ConnectionError(f"Failed to connect to Splunk: {str(e)}")


@mcp.tool()
def search_splunk(
    query: str,
    earliest_time: str = "-24h",
    latest_time: str = "now",
    max_count: int = 0
) -> dict[str, Any]:
    """
    Execute a search query in Splunk and return results.

    Args:
        query: The Splunk search query (SPL). Should start with 'search' or include a pipe command.
        earliest_time: Earliest time for search (e.g., '-24h', '-7d', '2024-01-01T00:00:00')
        latest_time: Latest time for search (e.g., 'now', '2024-01-31T23:59:59')
        max_count: Maximum number of results to return (default: 0, no limit)

    Returns:
        Dictionary containing search results and metadata
    """
    service = get_splunk_service()

    # Ensure query starts with 'search' if it doesn't already have a leading command
    if not query.strip().startswith(('search', '|', 'from', 'tstats', 'inputlookup')):
        query = f"search {query}"

    try:
        # Create search job (omit max_count for unlimited)
        job_kwargs = {
            "earliest_time": earliest_time,
            "latest_time": latest_time,
        }
        if max_count > 0:
            job_kwargs["max_count"] = max_count

        job = service.jobs.create(query, **job_kwargs)

        # Wait for job to complete
        while not job.is_done():
            pass

        # Get results with pagination for unlimited (max_count=0)
        search_results = []
        if max_count == 0:
            # Paginate through all results
            batch_size = 50000
            offset = 0
            while True:
                result_stream = job.results(count=batch_size, offset=offset)
                reader = results.ResultsReader(result_stream)
                batch = [r for r in reader if isinstance(r, dict)]
                if not batch:
                    break
                search_results.extend(batch)
                offset += len(batch)
                if len(batch) < batch_size:
                    break
        else:
            # Single fetch with specified count
            result_stream = job.results(count=max_count)
            reader = results.ResultsReader(result_stream)
            for result in reader:
                if isinstance(result, dict):
                    search_results.append(result)

        # Get job statistics
        stats = {
            "result_count": job["resultCount"],
            "scan_count": job["scanCount"],
            "event_count": job["eventCount"],
            "disk_usage": job["diskUsage"],
            "run_duration": job["runDuration"],
            "earliest_time": earliest_time,
            "latest_time": latest_time
        }

        # Clean up job
        job.cancel()

        return {
            "success": True,
            "results": search_results,
            "stats": stats,
            "result_count": len(search_results)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "results": []
        }


@mcp.tool()
def search_async(
    query: str,
    earliest_time: str = "-24h",
    latest_time: str = "now",
    max_count: int = 10000
) -> dict[str, Any]:
    """
    Execute a non-blocking async search and return the job ID immediately.

    Use this for long-running searches. Poll get_job_results() with the
    returned SID to retrieve results when the job completes.

    Args:
        query: The Splunk search query (SPL)
        earliest_time: Earliest time for search (e.g., '-24h', '-7d')
        latest_time: Latest time for search (e.g., 'now')
        max_count: Maximum number of results (default: 10000, 0 = no limit)

    Returns:
        Dictionary containing job SID for polling results
    """
    service = get_splunk_service()

    # Ensure query starts with 'search' if needed
    if not query.strip().startswith(('search', '|', 'from', 'tstats', 'inputlookup')):
        query = f"search {query}"

    try:
        # Create search job (non-blocking, omit max_count for unlimited)
        job_kwargs = {
            "earliest_time": earliest_time,
            "latest_time": latest_time,
        }
        if max_count > 0:
            job_kwargs["max_count"] = max_count

        job = service.jobs.create(query, **job_kwargs)

        return {
            "success": True,
            "message": "Search job created. Use get_job_results() to retrieve results.",
            "sid": job.sid,
            "query": query,
            "earliest_time": earliest_time,
            "latest_time": latest_time
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def search_realtime(
    query: str,
    window_seconds: int = 60,
    max_count: int = 100,
    timeout_seconds: int = 30
) -> dict[str, Any]:
    """
    Execute a real-time search with a sliding time window.

    Real-time searches continuously monitor incoming data. This function
    runs for the specified timeout and returns accumulated results.

    Args:
        query: The Splunk search query (SPL)
        window_seconds: Size of the real-time window in seconds (default: 60)
        max_count: Maximum number of results to return (default: 100)
        timeout_seconds: How long to run the search before returning (default: 30)

    Returns:
        Dictionary containing real-time search results
    """
    import time

    service = get_splunk_service()

    # Ensure query starts with 'search' if needed
    if not query.strip().startswith(('search', '|', 'from', 'tstats', 'inputlookup')):
        query = f"search {query}"

    try:
        # Create real-time search job
        job = service.jobs.create(
            query,
            earliest_time=f"rt-{window_seconds}s",
            latest_time="rt",
            search_mode="realtime"
        )

        # Collect results for timeout_seconds
        start_time = time.time()
        search_results = []

        while (time.time() - start_time) < timeout_seconds:
            # Get preview results
            result_stream = job.preview(count=max_count)
            reader = results.ResultsReader(result_stream)

            for result in reader:
                if isinstance(result, dict):
                    # Avoid duplicates
                    if result not in search_results:
                        search_results.append(result)

            if len(search_results) >= max_count:
                break

            time.sleep(1)

        # Cancel the real-time job
        job.cancel()

        return {
            "success": True,
            "results": search_results[:max_count],
            "result_count": len(search_results[:max_count]),
            "window_seconds": window_seconds,
            "collection_time_seconds": min(timeout_seconds, time.time() - start_time)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "results": []
        }


@mcp.tool()
def export_search_results(
    query: str,
    file_path: str,
    output_format: str = "csv",
    earliest_time: str = "-24h",
    latest_time: str = "now",
    max_count: int = 50000
) -> dict[str, Any]:
    """
    Execute a search and export results to a file.

    Args:
        query: The Splunk search query (SPL)
        file_path: Absolute path to save the exported file
        output_format: Export format - 'csv', 'json', or 'xml' (default: csv)
        earliest_time: Earliest time for search (e.g., '-24h', '-7d')
        latest_time: Latest time for search (e.g., 'now')
        max_count: Maximum number of results to export (default: 50000, 0 = no limit)

    Returns:
        Dictionary indicating success and file details
    """
    service = get_splunk_service()

    # Ensure query starts with 'search' if needed
    if not query.strip().startswith(('search', '|', 'from', 'tstats', 'inputlookup')):
        query = f"search {query}"

    # Validate output format
    if output_format not in ['csv', 'json', 'xml']:
        return {
            "success": False,
            "error": f"Invalid output format '{output_format}'. Must be 'csv', 'json', or 'xml'."
        }

    try:
        # Create search job (omit max_count for unlimited)
        job_kwargs = {
            "earliest_time": earliest_time,
            "latest_time": latest_time,
        }
        if max_count > 0:
            job_kwargs["max_count"] = max_count

        job = service.jobs.create(query, **job_kwargs)

        # Wait for job to complete
        while not job.is_done():
            pass

        # Get results with pagination for unlimited (max_count=0)
        if max_count == 0:
            batch_size = 50000
            offset = 0
            row_count = 0

            if output_format == 'csv':
                # CSV: fetch as JSON for reliable pagination, then write as CSV
                search_results = []
                while True:
                    result_stream = job.results(count=batch_size, offset=offset)
                    reader = results.ResultsReader(result_stream)
                    batch = [r for r in reader if isinstance(r, dict)]
                    if not batch:
                        break
                    search_results.extend(batch)
                    offset += len(batch)
                    if len(batch) < batch_size:
                        break

                # Write results as CSV
                if search_results:
                    with open(file_path, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=search_results[0].keys())
                        writer.writeheader()
                        writer.writerows(search_results)
                row_count = len(search_results)

            elif output_format == 'json':
                # JSON: paginate and collect all results
                search_results = []
                while True:
                    result_stream = job.results(count=batch_size, offset=offset)
                    reader = results.ResultsReader(result_stream)
                    batch = [r for r in reader if isinstance(r, dict)]
                    if not batch:
                        break
                    search_results.extend(batch)
                    offset += len(batch)
                    if len(batch) < batch_size:
                        break
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(search_results, f, indent=2, default=str)
                row_count = len(search_results)

            elif output_format == 'xml':
                # XML: paginate and collect all results, wrap in root element
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write('<?xml version="1.0" encoding="UTF-8"?>\n<results>\n')
                    while True:
                        result_stream = job.results(count=batch_size, offset=offset, output_mode='xml')
                        content = result_stream.read().decode('utf-8')
                        # Extract <result> elements from each batch
                        result_matches = re.findall(r'<result[^>]*>.*?</result>', content, re.DOTALL)
                        if not result_matches:
                            break
                        for match in result_matches:
                            f.write(match + '\n')
                        row_count += len(result_matches)
                        offset += len(result_matches)
                        if len(result_matches) < batch_size:
                            break
                    f.write('</results>\n')
        else:
            # Single fetch with specified count
            result_stream = job.results(count=max_count, output_mode=output_format)

            if output_format == 'csv':
                content = result_stream.read().decode('utf-8')
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    f.write(content)
                row_count = content.count('\n') - 1 if content else 0

            elif output_format == 'json':
                reader = results.ResultsReader(result_stream)
                search_results = []
                for result in reader:
                    if isinstance(result, dict):
                        search_results.append(result)
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(search_results, f, indent=2, default=str)
                row_count = len(search_results)

            elif output_format == 'xml':
                content = result_stream.read().decode('utf-8')
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                row_count = content.count('<result>')

        # Clean up job
        job.cancel()

        return {
            "success": True,
            "message": f"Results exported to {file_path}",
            "file_path": file_path,
            "output_format": output_format,
            "row_count": row_count
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def list_indexes() -> dict[str, Any]:
    """
    List all indexes available in Splunk.

    Returns:
        Dictionary containing list of indexes with their properties
    """
    service = get_splunk_service()

    try:
        indexes = []
        for index in service.indexes:
            indexes.append({
                "name": index.name,
                "total_event_count": index.content.get("totalEventCount", "N/A"),
                "current_db_size_mb": index.content.get("currentDBSizeMB", "N/A"),
                "max_time": index.content.get("maxTime", "N/A"),
                "min_time": index.content.get("minTime", "N/A"),
                "disabled": index.disabled
            })

        return {
            "success": True,
            "indexes": indexes,
            "count": len(indexes)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "indexes": []
        }


@mcp.tool()
def list_saved_searches() -> dict[str, Any]:
    """
    List all saved searches (reports and alerts) in Splunk.

    Returns:
        Dictionary containing list of saved searches with their properties
    """
    service = get_splunk_service()

    try:
        saved_searches = []
        for saved_search in service.saved_searches:
            saved_searches.append({
                "name": saved_search.name,
                "search": saved_search.content.get("search", ""),
                "is_scheduled": saved_search.content.get("is_scheduled", False),
                "cron_schedule": saved_search.content.get("cron_schedule", ""),
                "earliest_time": saved_search.content.get("dispatch.earliest_time", ""),
                "latest_time": saved_search.content.get("dispatch.latest_time", ""),
                "description": saved_search.content.get("description", "")
            })

        return {
            "success": True,
            "saved_searches": saved_searches,
            "count": len(saved_searches)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "saved_searches": []
        }


@mcp.tool()
def run_saved_search(name: str, max_count: int = 100) -> dict[str, Any]:
    """
    Execute a saved search by name and return its results.

    Args:
        name: Name of the saved search to execute
        max_count: Maximum number of results to return (default: 100)

    Returns:
        Dictionary containing saved search results and metadata
    """
    service = get_splunk_service()

    try:
        # Get the saved search
        saved_search = service.saved_searches[name]

        # Dispatch the saved search
        job = saved_search.dispatch()

        # Wait for job to complete
        while not job.is_done():
            pass

        # Get results
        result_stream = job.results(count=max_count)
        reader = results.ResultsReader(result_stream)

        search_results = []
        for result in reader:
            if isinstance(result, dict):
                search_results.append(result)

        # Get job statistics
        stats = {
            "result_count": job["resultCount"],
            "scan_count": job["scanCount"],
            "event_count": job["eventCount"],
            "run_duration": job["runDuration"]
        }

        # Clean up job
        job.cancel()

        return {
            "success": True,
            "saved_search_name": name,
            "results": search_results,
            "stats": stats,
            "result_count": len(search_results)
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Saved search '{name}' not found",
            "results": []
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "results": []
        }


@mcp.tool()
def get_saved_search(name: str) -> dict[str, Any]:
    """
    Get detailed information about a specific saved search.

    Args:
        name: Name of the saved search to retrieve

    Returns:
        Dictionary containing saved search details
    """
    service = get_splunk_service()

    try:
        saved_search = service.saved_searches[name]

        return {
            "success": True,
            "saved_search": {
                "name": saved_search.name,
                "search": saved_search.content.get("search", ""),
                "is_scheduled": saved_search.content.get("is_scheduled", False),
                "cron_schedule": saved_search.content.get("cron_schedule", ""),
                "earliest_time": saved_search.content.get("dispatch.earliest_time", ""),
                "latest_time": saved_search.content.get("dispatch.latest_time", ""),
                "description": saved_search.content.get("description", ""),
                "is_visible": saved_search.content.get("is_visible", True),
                "alert_type": saved_search.content.get("alert_type", ""),
                "alert_comparator": saved_search.content.get("alert_comparator", ""),
                "alert_threshold": saved_search.content.get("alert_threshold", ""),
                "actions": saved_search.content.get("actions", ""),
                "app": saved_search.access.app,
                "owner": saved_search.access.owner,
                "sharing": saved_search.access.sharing
            }
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Saved search '{name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_saved_search(
    name: str,
    search: str,
    description: Optional[str] = None,
    is_scheduled: bool = False,
    cron_schedule: Optional[str] = None,
    earliest_time: Optional[str] = None,
    latest_time: Optional[str] = None
) -> dict[str, Any]:
    """
    Create a new saved search (report) in Splunk.

    Args:
        name: Name of the saved search
        search: SPL search query
        description: Optional description of the saved search
        is_scheduled: Whether to schedule the search (default: False)
        cron_schedule: Cron schedule for running the search (e.g., '0 */4 * * *')
        earliest_time: Earliest time for the search (e.g., '-24h')
        latest_time: Latest time for the search (e.g., 'now')

    Returns:
        Dictionary indicating success or failure

    Note:
        Additional parameters from the Splunk REST API can be passed via the config dictionary.
        See https://docs.splunk.com/Documentation/Splunk/latest/RESTREF/RESTsearch
        for the complete list of available parameters.
    """
    service = get_splunk_service()

    try:
        # Prepare saved search configuration
        config = {
            "search": search,
            "is_scheduled": is_scheduled
        }

        if description:
            config["description"] = description

        if cron_schedule:
            config["cron_schedule"] = cron_schedule

        if earliest_time:
            config["dispatch.earliest_time"] = earliest_time

        if latest_time:
            config["dispatch.latest_time"] = latest_time

        # Create the saved search
        _ = service.saved_searches.create(name, **config)

        return {
            "success": True,
            "message": f"Saved search '{name}' created successfully",
            "saved_search_name": name
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def update_saved_search(
    name: str,
    search: Optional[str] = None,
    description: Optional[str] = None,
    is_scheduled: Optional[bool] = None,
    cron_schedule: Optional[str] = None,
    earliest_time: Optional[str] = None,
    latest_time: Optional[str] = None
) -> dict[str, Any]:
    """
    Update an existing saved search in Splunk.

    Args:
        name: Name of the saved search to update
        search: Optional new SPL search query
        description: Optional new description
        is_scheduled: Optional enable/disable scheduling
        cron_schedule: Optional new cron schedule
        earliest_time: Optional new earliest time
        latest_time: Optional new latest time

    Returns:
        Dictionary indicating success or failure

    Note:
        Additional parameters from the Splunk REST API can be passed via the update_dict.
        See https://docs.splunk.com/Documentation/Splunk/latest/RESTREF/RESTsearch
        for the complete list of available parameters.
    """
    service = get_splunk_service()

    try:
        saved_search = service.saved_searches[name]

        # Update only provided fields
        update_dict = {}
        if search is not None:
            update_dict["search"] = search
        if description is not None:
            update_dict["description"] = description
        if is_scheduled is not None:
            update_dict["is_scheduled"] = is_scheduled
        if cron_schedule is not None:
            update_dict["cron_schedule"] = cron_schedule
        if earliest_time is not None:
            update_dict["dispatch.earliest_time"] = earliest_time
        if latest_time is not None:
            update_dict["dispatch.latest_time"] = latest_time

        saved_search.update(**update_dict).refresh()

        return {
            "success": True,
            "message": f"Saved search '{name}' updated successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Saved search '{name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_saved_search(name: str) -> dict[str, Any]:
    """
    Delete a saved search from Splunk.

    Args:
        name: Name of the saved search to delete

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        saved_search = service.saved_searches[name]
        saved_search.delete()

        return {
            "success": True,
            "message": f"Saved search '{name}' deleted successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Saved search '{name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def get_index_info(index_name: str) -> dict[str, Any]:
    """
    Get detailed information about a specific index.

    Args:
        index_name: Name of the index to query

    Returns:
        Dictionary containing index details and statistics
    """
    service = get_splunk_service()

    try:
        index = service.indexes[index_name]

        info = {
            "name": index.name,
            "total_event_count": index.content.get("totalEventCount", "N/A"),
            "current_db_size_mb": index.content.get("currentDBSizeMB", "N/A"),
            "max_size": index.content.get("maxTotalDataSizeMB", "N/A"),
            "max_time": index.content.get("maxTime", "N/A"),
            "min_time": index.content.get("minTime", "N/A"),
            "disabled": index.disabled,
            "cold_path": index.content.get("coldPath", ""),
            "home_path": index.content.get("homePath", ""),
            "thawed_path": index.content.get("thawedPath", ""),
            "sync": index.content.get("sync", ""),
            "datatype": index.content.get("datatype", "")
        }

        return {
            "success": True,
            "index_info": info
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Index '{index_name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_index(
    name: str,
    datatype: str = "event",
    home_path: Optional[str] = None,
    cold_path: Optional[str] = None,
    thawed_path: Optional[str] = None,
    max_total_data_size_mb: Optional[int] = None,
    frozen_time_period_in_secs: Optional[int] = None,
    max_hot_buckets: Optional[int] = None,
    max_warm_db_count: Optional[int] = None
) -> dict[str, Any]:
    """
    Create a new index in Splunk.

    Args:
        name: Name of the index to create (must be unique)
        datatype: Type of data ('event' or 'metric', default: 'event')
        home_path: Path for hot/warm buckets (optional, uses default if not specified)
        cold_path: Path for cold buckets (optional, uses default if not specified)
        thawed_path: Path for thawed buckets (optional, uses default if not specified)
        max_total_data_size_mb: Maximum total size in MB (optional)
        frozen_time_period_in_secs: Time in seconds before data is frozen (optional)
        max_hot_buckets: Maximum number of hot buckets (optional)
        max_warm_db_count: Maximum number of warm buckets (optional)

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        # Prepare index configuration
        kwargs = {"datatype": datatype}

        if home_path:
            kwargs["homePath"] = home_path
        if cold_path:
            kwargs["coldPath"] = cold_path
        if thawed_path:
            kwargs["thawedPath"] = thawed_path
        if max_total_data_size_mb is not None:
            kwargs["maxTotalDataSizeMB"] = max_total_data_size_mb
        if frozen_time_period_in_secs is not None:
            kwargs["frozenTimePeriodInSecs"] = frozen_time_period_in_secs
        if max_hot_buckets is not None:
            kwargs["maxHotBuckets"] = max_hot_buckets
        if max_warm_db_count is not None:
            kwargs["maxWarmDBCount"] = max_warm_db_count

        # Create the index
        service.indexes.create(name, **kwargs)

        return {
            "success": True,
            "message": f"Index '{name}' created successfully",
            "index_name": name
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def update_index(
    name: str,
    max_total_data_size_mb: Optional[int] = None,
    frozen_time_period_in_secs: Optional[int] = None,
    max_hot_buckets: Optional[int] = None,
    max_warm_db_count: Optional[int] = None,
    disabled: Optional[bool] = None,
    min_raw_file_sync_secs: Optional[str] = None,
    max_hot_span_secs: Optional[int] = None
) -> dict[str, Any]:
    """
    Update an existing index in Splunk.

    Args:
        name: Name of the index to update
        max_total_data_size_mb: Maximum total size in MB
        frozen_time_period_in_secs: Time in seconds before data is frozen
        max_hot_buckets: Maximum number of hot buckets
        max_warm_db_count: Maximum number of warm buckets
        disabled: Enable/disable the index
        min_raw_file_sync_secs: Minimum raw file sync interval ('disable' or seconds)
        max_hot_span_secs: Maximum time span for hot buckets in seconds

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        index = service.indexes[name]

        # Build update dictionary with only provided values
        update_dict = {}
        if max_total_data_size_mb is not None:
            update_dict["maxTotalDataSizeMB"] = max_total_data_size_mb
        if frozen_time_period_in_secs is not None:
            update_dict["frozenTimePeriodInSecs"] = frozen_time_period_in_secs
        if max_hot_buckets is not None:
            update_dict["maxHotBuckets"] = max_hot_buckets
        if max_warm_db_count is not None:
            update_dict["maxWarmDBCount"] = max_warm_db_count
        if disabled is not None:
            update_dict["disabled"] = disabled
        if min_raw_file_sync_secs is not None:
            update_dict["minRawFileSyncSecs"] = min_raw_file_sync_secs
        if max_hot_span_secs is not None:
            update_dict["maxHotSpanSecs"] = max_hot_span_secs

        if not update_dict:
            return {
                "success": False,
                "error": "No update parameters provided"
            }

        index.update(**update_dict).refresh()

        return {
            "success": True,
            "message": f"Index '{name}' updated successfully",
            "updated_fields": list(update_dict.keys())
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Index '{name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_index(name: str) -> dict[str, Any]:
    """
    Delete an index from Splunk.

    WARNING: This permanently deletes the index and all its data.
    This operation cannot be undone.

    Args:
        name: Name of the index to delete

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        index = service.indexes[name]
        index.delete()

        return {
            "success": True,
            "message": f"Index '{name}' deleted successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Index '{name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def list_apps() -> dict[str, Any]:
    """
    List all apps installed in Splunk.

    Returns:
        Dictionary containing list of apps with their properties
    """
    service = get_splunk_service()

    try:
        apps = []
        for app in service.apps:
            apps.append({
                "name": app.name,
                "label": app.content.get("label", ""),
                "version": app.content.get("version", ""),
                "author": app.content.get("author", ""),
                "description": app.content.get("description", ""),
                "disabled": app.disabled,
                "visible": app.content.get("visible", True),
                "configured": app.content.get("configured", False)
            })

        return {
            "success": True,
            "apps": apps,
            "count": len(apps)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "apps": []
        }


@mcp.tool()
def create_app(
    name: str,
    label: Optional[str] = None,
    description: Optional[str] = None,
    author: Optional[str] = None,
    version: Optional[str] = None,
    visible: bool = True,
    template: str = "barebones"
) -> dict[str, Any]:
    """
    Create a new app in Splunk.

    Args:
        name: Technical name of the app (no spaces, used as folder name)
        label: Display name of the app (shown in UI)
        description: Optional description of the app
        author: Optional author name
        version: Optional version string (e.g., '1.0.0')
        visible: Whether the app is visible in the UI (default: True)
        template: App template to use ('barebones' or 'sample_app', default: 'barebones')

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        # Prepare app configuration
        kwargs = {
            "visible": visible,
            "template": template
        }

        if label:
            kwargs["label"] = label
        if description:
            kwargs["description"] = description
        if author:
            kwargs["author"] = author
        if version:
            kwargs["version"] = version

        # Create the app
        service.apps.create(name, **kwargs)

        return {
            "success": True,
            "message": f"App '{name}' created successfully",
            "app_name": name
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def update_app(
    name: str,
    label: Optional[str] = None,
    description: Optional[str] = None,
    author: Optional[str] = None,
    version: Optional[str] = None,
    visible: Optional[bool] = None,
    configured: Optional[bool] = None
) -> dict[str, Any]:
    """
    Update an existing app in Splunk.

    Args:
        name: Name of the app to update
        label: Optional new display name
        description: Optional new description
        author: Optional new author name
        version: Optional new version string
        visible: Optional visibility setting
        configured: Optional configured flag

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        app = service.apps[name]

        # Build update dictionary with only provided values
        update_dict = {}
        if label is not None:
            update_dict["label"] = label
        if description is not None:
            update_dict["description"] = description
        if author is not None:
            update_dict["author"] = author
        if version is not None:
            update_dict["version"] = version
        if visible is not None:
            update_dict["visible"] = visible
        if configured is not None:
            update_dict["configured"] = configured

        if not update_dict:
            return {
                "success": False,
                "error": "No update parameters provided"
            }

        app.update(**update_dict).refresh()

        return {
            "success": True,
            "message": f"App '{name}' updated successfully",
            "updated_fields": list(update_dict.keys())
        }

    except KeyError:
        return {
            "success": False,
            "error": f"App '{name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_app(name: str) -> dict[str, Any]:
    """
    Delete an app from Splunk.

    WARNING: This permanently deletes the app and all its configurations.
    This operation cannot be undone.

    Args:
        name: Name of the app to delete

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        app = service.apps[name]
        app.delete()

        # Check if restart is required after deletion
        restart_required = service.restart_required

        result = {
            "success": True,
            "message": f"App '{name}' deleted successfully",
            "restart_required": restart_required
        }

        if restart_required:
            result["note"] = "A Splunk restart is required to complete the app deletion"

        return result

    except KeyError:
        return {
            "success": False,
            "error": f"App '{name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def send_event(
    index: str,
    event: str,
    source: Optional[str] = None,
    sourcetype: Optional[str] = None,
    host: Optional[str] = None
) -> dict[str, Any]:
    """
    Send an event to a Splunk index.

    Args:
        index: Name of the index to send the event to
        event: The event data to send (can be JSON string or plain text)
        source: Optional source field for the event
        sourcetype: Optional sourcetype for the event
        host: Optional host field for the event

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        splunk_index = service.indexes[index]

        # Prepare event parameters
        kwargs = {}
        if source:
            kwargs['source'] = source
        if sourcetype:
            kwargs['sourcetype'] = sourcetype
        if host:
            kwargs['host'] = host

        # Submit event
        splunk_index.submit(event, **kwargs)

        return {
            "success": True,
            "message": f"Event successfully sent to index '{index}'",
            "index": index,
            "timestamp": datetime.now().isoformat()
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Index '{index}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def get_server_info() -> dict[str, Any]:
    """
    Get information about the Splunk server.

    Returns:
        Dictionary containing server information
    """
    service = get_splunk_service()

    try:
        info = service.info

        server_info = {
            "version": info.get("version", ""),
            "build": info.get("build", ""),
            "server_name": info.get("serverName", ""),
            "os_name": info.get("os_name", ""),
            "os_version": info.get("os_version", ""),
            "cpu_arch": info.get("cpu_arch", ""),
            "license_state": info.get("licenseState", ""),
            "license_labels": info.get("licenseLabels", []),
            "mode": info.get("mode", "")
        }

        return {
            "success": True,
            "server_info": server_info
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# Alert Management Tools
# ============================================================================

@mcp.tool()
def list_alerts() -> dict[str, Any]:
    """
    List all triggered alerts in Splunk.

    Returns:
        Dictionary containing list of triggered alerts with their properties
    """
    service = get_splunk_service()

    try:
        alerts = []
        for alert in service.fired_alerts:
            alerts.append({
                "name": alert.name,
                "sid": alert.content.get("sid", ""),
                "trigger_time": alert.content.get("trigger_time", ""),
                "triggered_alerts": alert.content.get("triggered_alerts", 0),
                "actions": alert.content.get("actions", ""),
                "alert_type": alert.content.get("alert_type", "")
            })

        return {
            "success": True,
            "alerts": alerts,
            "count": len(alerts)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "alerts": []
        }


@mcp.tool()
def create_alert(
    name: str,
    search: str,
    alert_type: str = "number of events",
    alert_comparator: str = "greater than",
    alert_threshold: str = "0",
    cron_schedule: str = "*/5 * * * *",
    actions: Optional[str] = None,
    description: Optional[str] = None
) -> dict[str, Any]:
    """
    Create a new alert in Splunk.

    Args:
        name: Name of the alert
        search: SPL search query for the alert
        alert_type: Type of alert condition.
            Valid values: 'number of events', 'number of results', 'number of hosts', 'number of sources'
            (default: 'number of events')
        alert_comparator: Comparison operator for the alert threshold.
            Valid values: 'greater than', 'less than', 'equal to', 'rises by', 'drops by', 'not equal to'
            (default: 'greater than')
        alert_threshold: Threshold value for triggering the alert (default: '0')
        cron_schedule: Cron schedule for running the alert (default: every 5 minutes '*/5 * * * *')
        actions: Comma-separated list of actions to trigger (e.g., 'email,script')
        description: Optional description of the alert

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        # Prepare alert configuration
        alert_config = {
            "search": search,
            "alert_type": alert_type,
            "alert_comparator": alert_comparator,
            "alert_threshold": alert_threshold,
            "cron_schedule": cron_schedule,
            "is_scheduled": True
        }

        if actions:
            alert_config["actions"] = actions

        if description:
            alert_config["description"] = description

        # Create the saved search (alert)
        _ = service.saved_searches.create(name, **alert_config)

        return {
            "success": True,
            "message": f"Alert '{name}' created successfully",
            "alert_name": name
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def update_alert(
    name: str,
    search: Optional[str] = None,
    alert_threshold: Optional[str] = None,
    cron_schedule: Optional[str] = None,
    actions: Optional[str] = None,
    is_scheduled: Optional[bool] = None
) -> dict[str, Any]:
    """
    Update an existing alert in Splunk.

    Args:
        name: Name of the alert to update
        search: Optional new SPL search query
        alert_threshold: Optional new threshold value
        cron_schedule: Optional new cron schedule
        actions: Optional new actions
        is_scheduled: Optional enable/disable scheduling

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        alert = service.saved_searches[name]

        # Update only provided fields
        update_dict = {}
        if search is not None:
            update_dict["search"] = search
        if alert_threshold is not None:
            update_dict["alert_threshold"] = alert_threshold
        if cron_schedule is not None:
            update_dict["cron_schedule"] = cron_schedule
        if actions is not None:
            update_dict["actions"] = actions
        if is_scheduled is not None:
            update_dict["is_scheduled"] = is_scheduled

        alert.update(**update_dict).refresh()

        return {
            "success": True,
            "message": f"Alert '{name}' updated successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Alert '{name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_alert(name: str) -> dict[str, Any]:
    """
    Delete an alert from Splunk.

    Args:
        name: Name of the alert to delete

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        alert = service.saved_searches[name]
        alert.delete()

        return {
            "success": True,
            "message": f"Alert '{name}' deleted successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Alert '{name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def get_alert_history(name: str, max_count: int = 50) -> dict[str, Any]:
    """
    Get the firing history of an alert.

    Note:
        This queries the _audit index. The authenticated user must have
        read access to the _audit index to retrieve alert history.

    Args:
        name: Name of the alert
        max_count: Maximum number of history entries to return

    Returns:
        Dictionary containing alert history
    """
    service = get_splunk_service()

    try:
        # Search for alert actions in the _audit index
        query = f'search index=_audit action="alert_fired" savedsearch_name="{name}"'
        job = service.jobs.create(
            query,
            earliest_time="-7d",
            latest_time="now",
            max_count=max_count
        )

        while not job.is_done():
            pass

        result_stream = job.results(count=max_count)
        reader = results.ResultsReader(result_stream)

        history = []
        for result in reader:
            if isinstance(result, dict):
                history.append(result)

        job.cancel()

        return {
            "success": True,
            "alert_name": name,
            "history": history,
            "count": len(history)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "history": []
        }


# ============================================================================
# Dashboard Management Tools
# ============================================================================

@mcp.tool()
def list_dashboards(owner: str = "-", app: str = "-") -> dict[str, Any]:
    """
    List all dashboards in Splunk.

    Args:
        owner: Filter by owner (default: all users)
        app: Filter by app (default: all apps)

    Returns:
        Dictionary containing list of dashboards with their properties
    """
    service = get_splunk_service()

    try:
        # Get dashboards with optional filtering in JSON format
        views = service.get('data/ui/views', owner=owner, app=app, count=0, output_mode='json')
        data = json.loads(views.body.read().decode('utf-8'))

        # Extract only essential fields for list operations
        dashboards = []
        for entry in data.get('entry', []):
            dashboards.append({
                "name": entry.get('name'),
                "label": entry.get('content', {}).get('label', ''),
                "description": entry.get('content', {}).get('description', ''),
                "author": entry.get('author'),
                "updated": entry.get('updated'),
                "app": entry.get('acl', {}).get('app', ''),
                "sharing": entry.get('acl', {}).get('sharing', '')
            })

        return {
            "success": True,
            "dashboards": dashboards,
            "count": len(dashboards)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "dashboards": []
        }


@mcp.tool()
def get_dashboard(name: str, owner: str = "-", app: str = "-") -> dict[str, Any]:
    """
    Get the XML/JSON content of a dashboard.

    Args:
        name: Name of the dashboard
        owner: Owner of the dashboard (default: all users)
        app: App containing the dashboard (default: all apps)

    Returns:
        Dictionary containing dashboard content
    """
    service = get_splunk_service()

    try:
        # Get dashboard in JSON format
        response = service.get(f'data/ui/views/{name}', owner=owner, app=app, output_mode='json')
        data = json.loads(response.body.read().decode('utf-8'))

        entries = data.get('entry', [])
        return {
            "success": True,
            "dashboard_name": name,
            "data": entries[0] if entries else {}
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_dashboard(
    name: str,
    xml_content: str,
    app: str = "search"
) -> dict[str, Any]:
    """
    Create a new dashboard in Splunk.

    Args:
        name: Technical name of the dashboard (no spaces)
        xml_content: XML content of the dashboard (must include <label> tag).
                    Do NOT include CDATA wrappers - pass plain XML only.
        app: App to create the dashboard in (default: search)

    Returns:
        Dictionary indicating success or failure

    Important:
        The xml_content must be well-formed XML starting with <dashboard> or <form>.
        The XML must include a <label> element. Do NOT wrap the XML in CDATA sections.

    Example:
        <dashboard>
          <label>My Dashboard</label>
          <row>
            <panel>
              <title>Sample Panel</title>
              <search>
                <query>index=main | head 10</query>
              </search>
            </panel>
          </row>
        </dashboard>
    """
    service = get_splunk_service()

    try:
        # Post to data/ui/views with app context
        service.post(
            'data/ui/views',
            app=app,
            name=name,
            **{"eai:data": xml_content}
        )

        return {
            "success": True,
            "message": f"Dashboard '{name}' created successfully",
            "dashboard_name": name
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_dashboard(name: str, app: str = "search") -> dict[str, Any]:
    """
    Delete a dashboard from Splunk.

    Args:
        name: Name of the dashboard to delete
        app: App containing the dashboard (default: search)

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        service.delete(f'data/ui/views/{name}', app=app)

        return {
            "success": True,
            "message": f"Dashboard '{name}' deleted successfully"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# Knowledge Object Tools (Lookups & Field Extractions)
# ============================================================================

@mcp.tool()
def list_lookups(app: str = "-") -> dict[str, Any]:
    """
    List all lookup table files in Splunk.

    Args:
        app: Specific app to list lookups from (default: all apps)

    Returns:
        Dictionary containing list of lookups
    """
    service = get_splunk_service()

    try:
        # Get lookup files in JSON format
        lookup_files = service.get('data/lookup-table-files', app=app, owner='-', count=-1, output_mode='json')
        data = json.loads(lookup_files.body.read().decode('utf-8'))

        # Extract only essential fields for list operations
        lookups = []
        for entry in data.get('entry', []):
            lookups.append({
                "name": entry.get('name'),
                "type": entry.get('content', {}).get('type', ''),
                "author": entry.get('author'),
                "updated": entry.get('updated'),
                "app": entry.get('acl', {}).get('app', ''),
                "sharing": entry.get('acl', {}).get('sharing', '')
            })

        return {
            "success": True,
            "lookups": lookups,
            "count": len(lookups)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "lookups": []
        }


@mcp.tool()
def get_lookup_data(lookup_name: str, max_rows: int = 1000) -> dict[str, Any]:
    """
    Retrieve data from a lookup table.

    Args:
        lookup_name: Name of the lookup table file
        max_rows: Maximum number of rows to return (default: 1000)

    Returns:
        Dictionary containing lookup data
    """
    service = get_splunk_service()

    try:
        # Use inputlookup to retrieve data
        query = f"| inputlookup {lookup_name}"
        job = service.jobs.create(query, max_count=max_rows)

        while not job.is_done():
            pass

        result_stream = job.results(count=max_rows)
        reader = results.ResultsReader(result_stream)

        lookup_data = []
        for result in reader:
            if isinstance(result, dict):
                lookup_data.append(result)

        job.cancel()

        return {
            "success": True,
            "lookup_name": lookup_name,
            "data": lookup_data,
            "row_count": len(lookup_data)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "data": []
        }


@mcp.tool()
def update_lookup_data(
    lookup_name: str,
    data: list[dict[str, Any]],
    app: str = "search"
) -> dict[str, Any]:
    """
    Update a lookup table with new data. This replaces all existing data.

    Args:
        lookup_name: Name of the lookup table file
        data: List of dictionaries containing the lookup data
        app: App containing the lookup (default: search)

    Returns:
        Dictionary indicating success or failure

    Note:
        The data is converted to CSV format automatically. All dictionaries in the list
        must have the same keys. The first dictionary's keys determine the CSV headers.
    """
    service = get_splunk_service()

    try:
        # Convert data to CSV format
        if not data:
            return {
                "success": False,
                "error": "No data provided"
            }

        # Get headers from first row
        headers = list(data[0].keys())
        csv_lines = [",".join(headers)]

        # Add data rows
        for row in data:
            csv_lines.append(",".join(str(row.get(h, "")) for h in headers))

        csv_content = "\n".join(csv_lines)

        # Upload the lookup file
        service.post(
            f'data/lookup-table-files/{lookup_name}',
            **{"eai:data": csv_content, "eai:appName": app}
        )

        return {
            "success": True,
            "message": f"Lookup '{lookup_name}' updated successfully",
            "rows_written": len(data)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def list_field_extractions(app: str = "search", max_results: int = 50) -> dict[str, Any]:
    """
    List all field extractions in Splunk.

    Args:
        app: Specific app to list field extractions from (default: search)
        max_results: Maximum number of results to return (default: 50)

    Returns:
        Dictionary containing list of field extractions
    """
    service = get_splunk_service()

    try:
        # Set namespace to specific app (SDK's confs collection requires specific namespace)
        service.namespace['app'] = app
        service.namespace['owner'] = 'nobody'

        # Access props.conf using the SDK's Configurations API
        props_conf = service.confs['props']

        # Get stanzas (field extractions) with limit
        stanzas = props_conf.list(count=max_results)

        extractions = []
        for stanza in stanzas:
            extractions.append({
                "name": stanza.name,
                "author": stanza.access.owner if hasattr(stanza, 'access') else 'N/A',
                "updated": stanza.state.updated if hasattr(stanza.state, 'updated') else 'N/A',
                "app": stanza.access.app if hasattr(stanza, 'access') else app,
                "sharing": stanza.access.sharing if hasattr(stanza, 'access') else 'N/A'
            })

        return {
            "success": True,
            "field_extractions": extractions,
            "count": len(extractions),
            "note": f"Showing up to {max_results} field extractions from app '{app}'."
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "field_extractions": []
        }


# ============================================================================
# Sourcetype & Transform Management Tools (props.conf / transforms.conf)
# ============================================================================

@mcp.tool()
def list_sourcetypes(app: str = "search", max_results: int = 100) -> dict[str, Any]:
    """
    List all sourcetype configurations in Splunk.

    Args:
        app: Specific app to list sourcetypes from (default: search)
        max_results: Maximum number of results to return (default: 100)

    Returns:
        Dictionary containing list of sourcetypes with their properties
    """
    service = get_splunk_service()

    try:
        # Set namespace to specific app
        service.namespace['app'] = app
        service.namespace['owner'] = 'nobody'

        # Access props.conf
        props_conf = service.confs['props']

        sourcetypes = []
        for stanza in props_conf.list(count=max_results):
            content = stanza.content if hasattr(stanza, 'content') else {}
            sourcetypes.append({
                "name": stanza.name,
                "time_format": content.get("TIME_FORMAT", ""),
                "line_breaker": content.get("LINE_BREAKER", ""),
                "should_linemerge": content.get("SHOULD_LINEMERGE", ""),
                "truncate": content.get("TRUNCATE", ""),
                "max_timestamp_lookahead": content.get("MAX_TIMESTAMP_LOOKAHEAD", ""),
                "app": stanza.access.app if hasattr(stanza, 'access') else app
            })

        return {
            "success": True,
            "sourcetypes": sourcetypes,
            "count": len(sourcetypes)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "sourcetypes": []
        }


@mcp.tool()
def get_sourcetype(name: str, app: str = "search") -> dict[str, Any]:
    """
    Get detailed configuration of a specific sourcetype.

    Args:
        name: Name of the sourcetype
        app: App containing the sourcetype (default: search)

    Returns:
        Dictionary containing sourcetype configuration
    """
    service = get_splunk_service()

    try:
        service.namespace['app'] = app
        service.namespace['owner'] = 'nobody'

        props_conf = service.confs['props']
        stanza = props_conf[name]

        content = stanza.content if hasattr(stanza, 'content') else {}

        return {
            "success": True,
            "sourcetype": {
                "name": stanza.name,
                "TIME_FORMAT": content.get("TIME_FORMAT", ""),
                "TIME_PREFIX": content.get("TIME_PREFIX", ""),
                "LINE_BREAKER": content.get("LINE_BREAKER", ""),
                "SHOULD_LINEMERGE": content.get("SHOULD_LINEMERGE", ""),
                "TRUNCATE": content.get("TRUNCATE", ""),
                "MAX_TIMESTAMP_LOOKAHEAD": content.get("MAX_TIMESTAMP_LOOKAHEAD", ""),
                "TZ": content.get("TZ", ""),
                "CHARSET": content.get("CHARSET", ""),
                "disabled": content.get("disabled", False),
                "app": stanza.access.app if hasattr(stanza, 'access') else app
            }
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Sourcetype '{name}' not found in app '{app}'"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_sourcetype(
    name: str,
    app: str = "search",
    time_format: Optional[str] = None,
    time_prefix: Optional[str] = None,
    line_breaker: Optional[str] = None,
    should_linemerge: Optional[bool] = None,
    truncate: Optional[int] = None,
    max_timestamp_lookahead: Optional[int] = None,
    tz: Optional[str] = None,
    charset: Optional[str] = None
) -> dict[str, Any]:
    """
    Create a new sourcetype configuration in props.conf.

    Args:
        name: Name of the sourcetype to create
        app: App to create the sourcetype in (default: search)
        time_format: strptime format for timestamps (e.g., '%Y-%m-%d %H:%M:%S')
        time_prefix: Regex pattern before timestamp
        line_breaker: Regex for line breaking (e.g., '([\\r\\n]+)')
        should_linemerge: Whether to merge multiple lines (default: True)
        truncate: Maximum line length before truncation
        max_timestamp_lookahead: How far into event to look for timestamp
        tz: Timezone for events (e.g., 'America/New_York')
        charset: Character encoding (e.g., 'UTF-8')

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        service.namespace['app'] = app
        service.namespace['owner'] = 'nobody'

        props_conf = service.confs['props']

        # Build configuration
        kwargs = {}
        if time_format:
            kwargs["TIME_FORMAT"] = time_format
        if time_prefix:
            kwargs["TIME_PREFIX"] = time_prefix
        if line_breaker:
            kwargs["LINE_BREAKER"] = line_breaker
        if should_linemerge is not None:
            kwargs["SHOULD_LINEMERGE"] = should_linemerge
        if truncate is not None:
            kwargs["TRUNCATE"] = truncate
        if max_timestamp_lookahead is not None:
            kwargs["MAX_TIMESTAMP_LOOKAHEAD"] = max_timestamp_lookahead
        if tz:
            kwargs["TZ"] = tz
        if charset:
            kwargs["CHARSET"] = charset

        props_conf.create(name, **kwargs)

        return {
            "success": True,
            "message": f"Sourcetype '{name}' created successfully in app '{app}'",
            "sourcetype_name": name
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def update_sourcetype(
    name: str,
    app: str = "search",
    time_format: Optional[str] = None,
    time_prefix: Optional[str] = None,
    line_breaker: Optional[str] = None,
    should_linemerge: Optional[bool] = None,
    truncate: Optional[int] = None,
    max_timestamp_lookahead: Optional[int] = None,
    tz: Optional[str] = None,
    charset: Optional[str] = None,
    disabled: Optional[bool] = None
) -> dict[str, Any]:
    """
    Update an existing sourcetype configuration.

    Args:
        name: Name of the sourcetype to update
        app: App containing the sourcetype (default: search)
        time_format: New strptime format for timestamps
        time_prefix: New regex pattern before timestamp
        line_breaker: New regex for line breaking
        should_linemerge: New line merge setting
        truncate: New maximum line length
        max_timestamp_lookahead: New timestamp lookahead value
        tz: New timezone
        charset: New character encoding
        disabled: Enable/disable the sourcetype

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        service.namespace['app'] = app
        service.namespace['owner'] = 'nobody'

        props_conf = service.confs['props']
        stanza = props_conf[name]

        # Build update dictionary
        update_dict = {}
        if time_format is not None:
            update_dict["TIME_FORMAT"] = time_format
        if time_prefix is not None:
            update_dict["TIME_PREFIX"] = time_prefix
        if line_breaker is not None:
            update_dict["LINE_BREAKER"] = line_breaker
        if should_linemerge is not None:
            update_dict["SHOULD_LINEMERGE"] = should_linemerge
        if truncate is not None:
            update_dict["TRUNCATE"] = truncate
        if max_timestamp_lookahead is not None:
            update_dict["MAX_TIMESTAMP_LOOKAHEAD"] = max_timestamp_lookahead
        if tz is not None:
            update_dict["TZ"] = tz
        if charset is not None:
            update_dict["CHARSET"] = charset
        if disabled is not None:
            update_dict["disabled"] = disabled

        if not update_dict:
            return {
                "success": False,
                "error": "No update parameters provided"
            }

        stanza.update(**update_dict).refresh()

        return {
            "success": True,
            "message": f"Sourcetype '{name}' updated successfully",
            "updated_fields": list(update_dict.keys())
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Sourcetype '{name}' not found in app '{app}'"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_sourcetype(name: str, app: str = "search") -> dict[str, Any]:
    """
    Delete a sourcetype configuration from props.conf.

    Args:
        name: Name of the sourcetype to delete
        app: App containing the sourcetype (default: search)

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        service.namespace['app'] = app
        service.namespace['owner'] = 'nobody'

        props_conf = service.confs['props']
        stanza = props_conf[name]
        stanza.delete()

        return {
            "success": True,
            "message": f"Sourcetype '{name}' deleted successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Sourcetype '{name}' not found in app '{app}'"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def list_transforms(app: str = "search", max_results: int = 100) -> dict[str, Any]:
    """
    List all field transforms in transforms.conf.

    Args:
        app: Specific app to list transforms from (default: search)
        max_results: Maximum number of results to return (default: 100)

    Returns:
        Dictionary containing list of transforms
    """
    service = get_splunk_service()

    try:
        service.namespace['app'] = app
        service.namespace['owner'] = 'nobody'

        transforms_conf = service.confs['transforms']

        transforms = []
        for stanza in transforms_conf.list(count=max_results):
            content = stanza.content if hasattr(stanza, 'content') else {}
            transforms.append({
                "name": stanza.name,
                "regex": content.get("REGEX", ""),
                "format": content.get("FORMAT", ""),
                "dest_key": content.get("DEST_KEY", ""),
                "source_key": content.get("SOURCE_KEY", ""),
                "app": stanza.access.app if hasattr(stanza, 'access') else app
            })

        return {
            "success": True,
            "transforms": transforms,
            "count": len(transforms)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "transforms": []
        }


@mcp.tool()
def get_transform(name: str, app: str = "search") -> dict[str, Any]:
    """
    Get detailed configuration of a specific transform.

    Args:
        name: Name of the transform
        app: App containing the transform (default: search)

    Returns:
        Dictionary containing transform configuration
    """
    service = get_splunk_service()

    try:
        service.namespace['app'] = app
        service.namespace['owner'] = 'nobody'

        transforms_conf = service.confs['transforms']
        stanza = transforms_conf[name]

        content = stanza.content if hasattr(stanza, 'content') else {}

        return {
            "success": True,
            "transform": {
                "name": stanza.name,
                "REGEX": content.get("REGEX", ""),
                "FORMAT": content.get("FORMAT", ""),
                "DEST_KEY": content.get("DEST_KEY", ""),
                "SOURCE_KEY": content.get("SOURCE_KEY", ""),
                "WRITE_META": content.get("WRITE_META", ""),
                "DEFAULT_VALUE": content.get("DEFAULT_VALUE", ""),
                "MV_ADD": content.get("MV_ADD", ""),
                "disabled": content.get("disabled", False),
                "app": stanza.access.app if hasattr(stanza, 'access') else app
            }
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Transform '{name}' not found in app '{app}'"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_transform(
    name: str,
    app: str = "search",
    regex: Optional[str] = None,
    format: Optional[str] = None,
    dest_key: Optional[str] = None,
    source_key: Optional[str] = None,
    write_meta: Optional[bool] = None,
    default_value: Optional[str] = None,
    mv_add: Optional[bool] = None
) -> dict[str, Any]:
    """
    Create a new field transform in transforms.conf.

    Args:
        name: Name of the transform to create
        app: App to create the transform in (default: search)
        regex: Regular expression for field extraction
        format: Format string for extracted fields (e.g., '$1::$2')
        dest_key: Destination key for the transform
        source_key: Source key to apply regex to (default: _raw)
        write_meta: Whether to write to metadata
        default_value: Default value if no match
        mv_add: Whether to append to multi-value fields

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        service.namespace['app'] = app
        service.namespace['owner'] = 'nobody'

        transforms_conf = service.confs['transforms']

        # Build configuration
        kwargs = {}
        if regex:
            kwargs["REGEX"] = regex
        if format:
            kwargs["FORMAT"] = format
        if dest_key:
            kwargs["DEST_KEY"] = dest_key
        if source_key:
            kwargs["SOURCE_KEY"] = source_key
        if write_meta is not None:
            kwargs["WRITE_META"] = write_meta
        if default_value:
            kwargs["DEFAULT_VALUE"] = default_value
        if mv_add is not None:
            kwargs["MV_ADD"] = mv_add

        transforms_conf.create(name, **kwargs)

        return {
            "success": True,
            "message": f"Transform '{name}' created successfully in app '{app}'",
            "transform_name": name
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def update_transform(
    name: str,
    app: str = "search",
    regex: Optional[str] = None,
    format: Optional[str] = None,
    dest_key: Optional[str] = None,
    source_key: Optional[str] = None,
    write_meta: Optional[bool] = None,
    default_value: Optional[str] = None,
    mv_add: Optional[bool] = None,
    disabled: Optional[bool] = None
) -> dict[str, Any]:
    """
    Update an existing field transform.

    Args:
        name: Name of the transform to update
        app: App containing the transform (default: search)
        regex: New regular expression
        format: New format string
        dest_key: New destination key
        source_key: New source key
        write_meta: New write_meta setting
        default_value: New default value
        mv_add: New mv_add setting
        disabled: Enable/disable the transform

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        service.namespace['app'] = app
        service.namespace['owner'] = 'nobody'

        transforms_conf = service.confs['transforms']
        stanza = transforms_conf[name]

        # Build update dictionary
        update_dict = {}
        if regex is not None:
            update_dict["REGEX"] = regex
        if format is not None:
            update_dict["FORMAT"] = format
        if dest_key is not None:
            update_dict["DEST_KEY"] = dest_key
        if source_key is not None:
            update_dict["SOURCE_KEY"] = source_key
        if write_meta is not None:
            update_dict["WRITE_META"] = write_meta
        if default_value is not None:
            update_dict["DEFAULT_VALUE"] = default_value
        if mv_add is not None:
            update_dict["MV_ADD"] = mv_add
        if disabled is not None:
            update_dict["disabled"] = disabled

        if not update_dict:
            return {
                "success": False,
                "error": "No update parameters provided"
            }

        stanza.update(**update_dict).refresh()

        return {
            "success": True,
            "message": f"Transform '{name}' updated successfully",
            "updated_fields": list(update_dict.keys())
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Transform '{name}' not found in app '{app}'"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_transform(name: str, app: str = "search") -> dict[str, Any]:
    """
    Delete a field transform from transforms.conf.

    Args:
        name: Name of the transform to delete
        app: App containing the transform (default: search)

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        service.namespace['app'] = app
        service.namespace['owner'] = 'nobody'

        transforms_conf = service.confs['transforms']
        stanza = transforms_conf[name]
        stanza.delete()

        return {
            "success": True,
            "message": f"Transform '{name}' deleted successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Transform '{name}' not found in app '{app}'"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# Modular Input Tools
# ============================================================================

@mcp.tool()
def list_inputs() -> dict[str, Any]:
    """
    List all data inputs configured in Splunk.

    Returns:
        Dictionary containing list of inputs
    """
    service = get_splunk_service()

    try:
        inputs = []

        # Get all input types
        for input in service.inputs:
            inputs.append({
                "name": input.name,
                "kind": input.kind,
                "disabled": input.content.get("disabled", False),
                "index": input.content.get("index", ""),
                "sourcetype": input.content.get("sourcetype", "")
            })

        return {
            "success": True,
            "inputs": inputs,
            "count": len(inputs)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "inputs": []
        }


@mcp.tool()
def get_input_info(input_name: str, input_kind: str) -> dict[str, Any]:
    """
    Get detailed information about a specific data input.

    Args:
        input_name: Name of the input
        input_kind: Kind/type of input (e.g., 'tcp', 'udp', 'monitor', 'script')

    Returns:
        Dictionary containing input details
    """
    service = get_splunk_service()

    try:
        input_obj = service.inputs[input_name, input_kind]

        info = {
            "name": input_obj.name,
            "kind": input_obj.kind,
            "disabled": input_obj.content.get("disabled", False),
            "index": input_obj.content.get("index", ""),
            "sourcetype": input_obj.content.get("sourcetype", ""),
            "source": input_obj.content.get("source", ""),
            "host": input_obj.content.get("host", "")
        }

        # Add kind-specific attributes
        for key, value in input_obj.content.items():
            if key not in info:
                info[key] = value

        return {
            "success": True,
            "input_info": info
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Input '{input_name}' of kind '{input_kind}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_monitor_input(
    path: str,
    index: str = "main",
    sourcetype: Optional[str] = None,
    whitelist: Optional[str] = None,
    blacklist: Optional[str] = None
) -> dict[str, Any]:
    """
    Create a file/directory monitoring input.

    Args:
        path: Path to monitor
        index: Index to send data to (default: main)
        sourcetype: Sourcetype for the data
        whitelist: Regex pattern for files to include
        blacklist: Regex pattern for files to exclude

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        kwargs = {"index": index}
        if sourcetype:
            kwargs["sourcetype"] = sourcetype
        if whitelist:
            kwargs["whitelist"] = whitelist
        if blacklist:
            kwargs["blacklist"] = blacklist

        service.inputs.create(path, "monitor", **kwargs)

        return {
            "success": True,
            "message": f"Monitor input created for path '{path}'",
            "path": path
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_input(input_name: str, input_kind: str) -> dict[str, Any]:
    """
    Delete a data input.

    Args:
        input_name: Name of the input to delete
        input_kind: Kind/type of input

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        input_obj = service.inputs[input_name, input_kind]
        input_obj.delete()

        return {
            "success": True,
            "message": f"Input '{input_name}' deleted successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Input '{input_name}' of kind '{input_kind}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# User & Access Management Tools
# ============================================================================

@mcp.tool()
def list_users() -> dict[str, Any]:
    """
    List all users in Splunk.

    Returns:
        Dictionary containing list of users
    """
    service = get_splunk_service()

    try:
        users = []
        for user in service.users:
            users.append({
                "name": user.name,
                "full_name": user.content.get("realname", ""),
                "email": user.content.get("email", ""),
                "roles": user.content.get("roles", []),
                "default_app": user.content.get("defaultApp", ""),
                "timezone": user.content.get("tz", "")
            })

        return {
            "success": True,
            "users": users,
            "count": len(users)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "users": []
        }


@mcp.tool()
def get_user_info(username: str) -> dict[str, Any]:
    """
    Get detailed information about a specific user.

    Args:
        username: Username to query

    Returns:
        Dictionary containing user details
    """
    service = get_splunk_service()

    try:
        user = service.users[username]

        info = {
            "name": user.name,
            "full_name": user.content.get("realname", ""),
            "email": user.content.get("email", ""),
            "roles": user.content.get("roles", []),
            "default_app": user.content.get("defaultApp", ""),
            "timezone": user.content.get("tz", ""),
            "type": user.content.get("type", "")
        }

        return {
            "success": True,
            "user_info": info
        }

    except KeyError:
        return {
            "success": False,
            "error": f"User '{username}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_user(
    username: str,
    password: str,
    roles: list[str],
    email: Optional[str] = None,
    realname: Optional[str] = None,
    default_app: Optional[str] = None,
    tz: Optional[str] = None
) -> dict[str, Any]:
    """
    Create a new user in Splunk.

    Args:
        username: Username for the new user (must be unique)
        password: Password for the user
        roles: List of roles to assign to the user (e.g., ['user', 'power'])
        email: Optional email address
        realname: Optional full name of the user
        default_app: Optional default app for the user
        tz: Optional timezone (e.g., 'America/New_York')

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        # Prepare user configuration
        kwargs = {
            "password": password,
            "roles": roles
        }

        if email:
            kwargs["email"] = email
        if realname:
            kwargs["realname"] = realname
        if default_app:
            kwargs["defaultApp"] = default_app
        if tz:
            kwargs["tz"] = tz

        # Create the user
        service.users.create(username, **kwargs)

        return {
            "success": True,
            "message": f"User '{username}' created successfully",
            "username": username
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def update_user(
    username: str,
    password: Optional[str] = None,
    roles: Optional[list[str]] = None,
    email: Optional[str] = None,
    realname: Optional[str] = None,
    default_app: Optional[str] = None,
    tz: Optional[str] = None
) -> dict[str, Any]:
    """
    Update an existing user in Splunk.

    Args:
        username: Username of the user to update
        password: Optional new password
        roles: Optional new list of roles
        email: Optional new email address
        realname: Optional new full name
        default_app: Optional new default app
        tz: Optional new timezone

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        user = service.users[username]

        # Build update dictionary with only provided values
        update_dict = {}
        if password is not None:
            update_dict["password"] = password
        if roles is not None:
            update_dict["roles"] = roles
        if email is not None:
            update_dict["email"] = email
        if realname is not None:
            update_dict["realname"] = realname
        if default_app is not None:
            update_dict["defaultApp"] = default_app
        if tz is not None:
            update_dict["tz"] = tz

        if not update_dict:
            return {
                "success": False,
                "error": "No update parameters provided"
            }

        user.update(**update_dict).refresh()

        return {
            "success": True,
            "message": f"User '{username}' updated successfully",
            "updated_fields": list(update_dict.keys())
        }

    except KeyError:
        return {
            "success": False,
            "error": f"User '{username}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_user(username: str) -> dict[str, Any]:
    """
    Delete a user from Splunk.

    Args:
        username: Username of the user to delete

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        user = service.users[username]
        user.delete()

        return {
            "success": True,
            "message": f"User '{username}' deleted successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"User '{username}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def list_roles() -> dict[str, Any]:
    """
    List all roles in Splunk.

    Returns:
        Dictionary containing list of roles with their capabilities
    """
    service = get_splunk_service()

    try:
        roles = []
        for role in service.roles:
            roles.append({
                "name": role.name,
                "capabilities": role.content.get("capabilities", []),
                "imported_roles": role.content.get("imported_roles", []),
                "search_filter": role.content.get("srchFilter", ""),
                "default_app": role.content.get("defaultApp", "")
            })

        return {
            "success": True,
            "roles": roles,
            "count": len(roles)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "roles": []
        }


@mcp.tool()
def get_role_info(role_name: str) -> dict[str, Any]:
    """
    Get detailed information about a specific role.

    Args:
        role_name: Name of the role to query

    Returns:
        Dictionary containing role details
    """
    service = get_splunk_service()

    try:
        role = service.roles[role_name]

        info = {
            "name": role.name,
            "capabilities": role.content.get("capabilities", []),
            "imported_roles": role.content.get("imported_roles", []),
            "search_filter": role.content.get("srchFilter", ""),
            "search_disk_quota": role.content.get("srchDiskQuota", ""),
            "search_jobs_quota": role.content.get("srchJobsQuota", ""),
            "default_app": role.content.get("defaultApp", ""),
            "imported_capabilities": role.content.get("imported_capabilities", [])
        }

        return {
            "success": True,
            "role_info": info
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Role '{role_name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_role(
    name: str,
    capabilities: Optional[list[str]] = None,
    imported_roles: Optional[list[str]] = None,
    default_app: Optional[str] = None,
    srch_filter: Optional[str] = None,
    srch_indexes_allowed: Optional[list[str]] = None,
    srch_indexes_default: Optional[list[str]] = None,
    srch_jobs_quota: Optional[int] = None,
    srch_disk_quota: Optional[int] = None
) -> dict[str, Any]:
    """
    Create a new role in Splunk.

    Args:
        name: Name of the role to create (must be unique)
        capabilities: List of capabilities to grant (e.g., ['search', 'schedule_search'])
        imported_roles: List of roles to inherit from (e.g., ['user', 'power'])
        default_app: Default app for users with this role
        srch_filter: Search filter to restrict searches
        srch_indexes_allowed: List of indexes this role can search
        srch_indexes_default: List of default indexes for searches
        srch_jobs_quota: Maximum number of concurrent search jobs
        srch_disk_quota: Maximum disk space usage in MB

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        # Prepare role configuration
        kwargs = {}

        if capabilities:
            kwargs["capabilities"] = capabilities
        if imported_roles:
            kwargs["imported_roles"] = imported_roles
        if default_app:
            kwargs["defaultApp"] = default_app
        if srch_filter:
            kwargs["srchFilter"] = srch_filter
        if srch_indexes_allowed:
            kwargs["srchIndexesAllowed"] = srch_indexes_allowed
        if srch_indexes_default:
            kwargs["srchIndexesDefault"] = srch_indexes_default
        if srch_jobs_quota is not None:
            kwargs["srchJobsQuota"] = srch_jobs_quota
        if srch_disk_quota is not None:
            kwargs["srchDiskQuota"] = srch_disk_quota

        # Create the role
        service.roles.create(name, **kwargs)

        return {
            "success": True,
            "message": f"Role '{name}' created successfully",
            "role_name": name
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def update_role(
    name: str,
    capabilities: Optional[list[str]] = None,
    imported_roles: Optional[list[str]] = None,
    default_app: Optional[str] = None,
    srch_filter: Optional[str] = None,
    srch_indexes_allowed: Optional[list[str]] = None,
    srch_indexes_default: Optional[list[str]] = None,
    srch_jobs_quota: Optional[int] = None,
    srch_disk_quota: Optional[int] = None
) -> dict[str, Any]:
    """
    Update an existing role in Splunk.

    Args:
        name: Name of the role to update
        capabilities: Optional new list of capabilities
        imported_roles: Optional new list of inherited roles
        default_app: Optional new default app
        srch_filter: Optional new search filter
        srch_indexes_allowed: Optional new list of allowed indexes
        srch_indexes_default: Optional new list of default indexes
        srch_jobs_quota: Optional new search jobs quota
        srch_disk_quota: Optional new disk quota in MB

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        role = service.roles[name]

        # Build update dictionary with only provided values
        update_dict = {}
        if capabilities is not None:
            update_dict["capabilities"] = capabilities
        if imported_roles is not None:
            update_dict["imported_roles"] = imported_roles
        if default_app is not None:
            update_dict["defaultApp"] = default_app
        if srch_filter is not None:
            update_dict["srchFilter"] = srch_filter
        if srch_indexes_allowed is not None:
            update_dict["srchIndexesAllowed"] = srch_indexes_allowed
        if srch_indexes_default is not None:
            update_dict["srchIndexesDefault"] = srch_indexes_default
        if srch_jobs_quota is not None:
            update_dict["srchJobsQuota"] = srch_jobs_quota
        if srch_disk_quota is not None:
            update_dict["srchDiskQuota"] = srch_disk_quota

        if not update_dict:
            return {
                "success": False,
                "error": "No update parameters provided"
            }

        role.update(**update_dict).refresh()

        return {
            "success": True,
            "message": f"Role '{name}' updated successfully",
            "updated_fields": list(update_dict.keys())
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Role '{name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_role(name: str) -> dict[str, Any]:
    """
    Delete a role from Splunk.

    WARNING: Deleting a role will affect all users assigned to this role.

    Args:
        name: Name of the role to delete

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        role = service.roles[name]
        role.delete()

        return {
            "success": True,
            "message": f"Role '{name}' deleted successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Role '{name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# KV Store Operation Tools
# ============================================================================

@mcp.tool()
def list_kvstore_collections(app: str = "-") -> dict[str, Any]:
    """
    List all KV Store collections.

    Args:
        app: Specific app to list collections from (default: all apps)

    Returns:
        Dictionary containing list of collections
    """
    service = get_splunk_service()

    try:
        # Set the namespace for the app if not listing all apps
        # The "-" value means all apps and shouldn't set namespace
        if app != "-":
            service.namespace['app'] = app

        collections = []
        kvstore = service.kvstore

        for collection in kvstore:
            collections.append({
                "name": collection.name,
                "app": collection.access.app if hasattr(collection.access, 'app') else app
            })

        return {
            "success": True,
            "collections": collections,
            "count": len(collections)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "collections": []
        }


@mcp.tool()
def get_kvstore_collection(
    collection_name: str,
    app: str = "search"
) -> dict[str, Any]:
    """
    Get detailed information about a KV Store collection, including its schema.

    Args:
        collection_name: Name of the collection
        app: App containing the collection (default: search)

    Returns:
        Dictionary containing collection details and schema
    """
    service = get_splunk_service()

    try:
        service.namespace['app'] = app

        collection = service.kvstore[collection_name]

        # Get collection properties
        info = {
            "name": collection.name,
            "app": collection.access.app if hasattr(collection, 'access') else app,
            "owner": collection.access.owner if hasattr(collection, 'access') else 'nobody'
        }

        # Try to get the schema/fields from the collection
        if hasattr(collection, 'content'):
            content = collection.content
            info["fields"] = content.get("field", {})
            info["accelerated_fields"] = content.get("accelerated_fields", {})

        return {
            "success": True,
            "collection": info
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Collection '{collection_name}' not found in app '{app}'"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_kvstore_collection(
    collection_name: str,
    app: str = "search",
    fields: Optional[dict[str, str]] = None,
    accelerated_fields: Optional[dict[str, str]] = None
) -> dict[str, Any]:
    """
    Create a new KV Store collection.

    Args:
        collection_name: Name of the collection to create
        app: App to create the collection in (default: search)
        fields: Optional dictionary of field definitions.
                Keys are field names, values are types ('string', 'number', 'bool', 'time', 'cidr')
                Example: {"name": "string", "count": "number", "active": "bool"}
        accelerated_fields: Optional dictionary of accelerated field definitions for indexing.
                Keys are acceleration names, values are JSON acceleration specs.
                Example: {"my_accel": "{\\"name\\": 1}"}

    Returns:
        Dictionary indicating success or failure

    Note:
        Field types supported by Splunk KV Store:
        - string: Text data
        - number: Numeric data (integer or float)
        - bool: Boolean (true/false)
        - time: Timestamp
        - cidr: CIDR network notation

    Important:
        This creates only the KV Store collection. To access data via SPL commands
        like '| inputlookup' or '| lookup', you must ALSO create a lookup definition
        in transforms.conf that references this collection. Use 'create_kvstore_lookup'
        instead if you need SPL access, as it creates both the collection and the
        lookup definition in one step.
    """
    service = get_splunk_service()

    try:
        service.namespace['app'] = app
        service.namespace['owner'] = 'nobody'

        # Build configuration
        kwargs = {}

        # Add field definitions if provided
        if fields:
            for field_name, field_type in fields.items():
                kwargs[f"field.{field_name}"] = field_type

        # Add accelerated fields if provided
        if accelerated_fields:
            for accel_name, accel_spec in accelerated_fields.items():
                kwargs[f"accelerated_fields.{accel_name}"] = accel_spec

        # Create the collection
        service.kvstore.create(collection_name, **kwargs)

        return {
            "success": True,
            "message": f"KV Store collection '{collection_name}' created successfully in app '{app}'",
            "collection_name": collection_name
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_kvstore_collection(
    collection_name: str,
    app: str = "search"
) -> dict[str, Any]:
    """
    Delete a KV Store collection and all its data.

    WARNING: This permanently deletes the collection and all data it contains.
    This operation cannot be undone.

    Args:
        collection_name: Name of the collection to delete
        app: App containing the collection (default: search)

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        service.namespace['app'] = app

        collection = service.kvstore[collection_name]
        collection.delete()

        return {
            "success": True,
            "message": f"KV Store collection '{collection_name}' deleted successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Collection '{collection_name}' not found in app '{app}'"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_kvstore_lookup(
    lookup_name: str,
    collection_name: Optional[str] = None,
    fields: Optional[dict[str, str]] = None,
    app: str = "search"
) -> dict[str, Any]:
    """
    Create a KV Store collection AND its lookup definition for SPL access.

    This is a convenience tool that creates both:
    1. The KV Store collection (data storage)
    2. The lookup definition in transforms.conf (enables SPL access)

    After creation, you can use:
    - '| inputlookup <lookup_name>' to read data
    - '| outputlookup <lookup_name>' to write data
    - '| lookup <lookup_name> ...' for lookups in searches

    Args:
        lookup_name: Name for the lookup (used in SPL commands)
        collection_name: Name for the KV Store collection (defaults to lookup_name if not provided)
        fields: Optional dictionary of field definitions.
                Keys are field names, values are types ('string', 'number', 'bool', 'time', 'cidr')
                Example: {"name": "string", "count": "number", "active": "bool"}
        app: App to create the lookup in (default: search)

    Returns:
        Dictionary indicating success or failure

    Example:
        create_kvstore_lookup(
            lookup_name="my_lookup",
            fields={"username": "string", "login_count": "number", "is_admin": "bool"}
        )
        # Then use in SPL:
        # | inputlookup my_lookup
        # | outputlookup my_lookup
    """
    service = get_splunk_service()

    # Use lookup_name as collection_name if not specified
    if collection_name is None:
        collection_name = lookup_name

    try:
        service.namespace['app'] = app
        service.namespace['owner'] = 'nobody'

        # Step 1: Create the KV Store collection
        kwargs = {}
        if fields:
            for field_name, field_type in fields.items():
                kwargs[f"field.{field_name}"] = field_type

        service.kvstore.create(collection_name, **kwargs)

        # Step 2: Create the lookup definition in transforms.conf
        transforms_conf = service.confs['transforms']

        # Build fields_list from the fields dictionary
        fields_list = "_key"  # Always include _key
        if fields:
            fields_list += "," + ",".join(fields.keys())

        # Create the lookup definition
        transforms_conf.create(lookup_name, **{
            "external_type": "kvstore",
            "collection": collection_name,
            "fields_list": fields_list
        })

        return {
            "success": True,
            "message": f"KV Store lookup '{lookup_name}' created successfully",
            "lookup_name": lookup_name,
            "collection_name": collection_name,
            "app": app,
            "fields": list(fields.keys()) if fields else [],
            "usage": {
                "read": f"| inputlookup {lookup_name}",
                "write": f"| outputlookup {lookup_name}",
                "lookup": f"| lookup {lookup_name} <field> OUTPUT <field>"
            }
        }

    except Exception as e:
        # Attempt cleanup if collection was created but transforms failed
        try:
            service.kvstore[collection_name].delete()
        except:
            pass
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def query_kvstore_collection(
    collection_name: str,
    query: Optional[dict[str, Any]] = None,
    limit: int = 1000,
    app: str = "search"
) -> dict[str, Any]:
    """
    Query data from a KV Store collection.

    Args:
        collection_name: Name of the collection
        query: Optional JSON query filter (MongoDB-style) as a dictionary
        limit: Maximum number of records to return (default: 1000)
        app: App containing the collection (default: search)

    Returns:
        Dictionary containing query results

    Example query filters:
        - Simple equality: {"status": "active"}
        - Comparison: {"count": {"$gt": 100}}
        - Multiple conditions: {"status": "active", "priority": {"$gte": 5}}
    """
    service = get_splunk_service()

    try:
        # Set the namespace for the app
        service.namespace['app'] = app

        # Access the KV Store collection using the proper SDK API
        collection = service.kvstore[collection_name]

        # Query the collection data
        query_params = {'limit': limit}
        if query:
            # The SDK expects a dict which it will JSON-encode
            query_params['query'] = query

        data = collection.data.query(**query_params)

        return {
            "success": True,
            "collection_name": collection_name,
            "data": data,
            "record_count": len(data)
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Collection '{collection_name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "data": []
        }


@mcp.tool()
def insert_kvstore_data(
    collection_name: str,
    data: dict[str, Any],
    app: str = "search"
) -> dict[str, Any]:
    """
    Insert a record into a KV Store collection.

    Args:
        collection_name: Name of the collection
        data: Dictionary containing the record data
        app: App containing the collection (default: search)

    Returns:
        Dictionary indicating success and the record key
    """
    service = get_splunk_service()

    try:
        # Set the namespace for the app
        service.namespace['app'] = app

        # Access the KV Store collection using the proper SDK API
        collection = service.kvstore[collection_name]

        # Insert data using the SDK's insert method
        result = collection.data.insert(data)

        return {
            "success": True,
            "collection_name": collection_name,
            "key": result.get("_key", "") if isinstance(result, dict) else str(result),
            "message": "Record inserted successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Collection '{collection_name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def update_kvstore_data(
    collection_name: str,
    key: str,
    data: dict[str, Any],
    app: str = "search"
) -> dict[str, Any]:
    """
    Update a record in a KV Store collection.

    Args:
        collection_name: Name of the collection
        key: Key (_key) of the record to update
        data: Dictionary containing the updated record data
        app: App containing the collection (default: search)

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        # Set the namespace for the app
        service.namespace['app'] = app

        # Access the KV Store collection using the proper SDK API
        collection = service.kvstore[collection_name]

        # Update data using the SDK's update method
        result = collection.data.update(key, data)

        return {
            "success": True,
            "collection_name": collection_name,
            "key": result.get("_key", key) if isinstance(result, dict) else key,
            "message": "Record updated successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Collection '{collection_name}' or key '{key}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_kvstore_data(
    collection_name: str,
    key: str,
    app: str = "search"
) -> dict[str, Any]:
    """
    Delete a record from a KV Store collection.

    Args:
        collection_name: Name of the collection
        key: Key (_key) of the record to delete
        app: App containing the collection (default: search)

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        # Set the namespace for the app
        service.namespace['app'] = app

        # Access the KV Store collection using the proper SDK API
        collection = service.kvstore[collection_name]

        # Delete data using the SDK's delete_by_id method
        collection.data.delete_by_id(key)

        return {
            "success": True,
            "collection_name": collection_name,
            "key": key,
            "message": "Record deleted successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Collection '{collection_name}' or key '{key}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# Data Model Tools
# ============================================================================

@mcp.tool()
def list_data_models(app: str = "-") -> dict[str, Any]:
    """
    List all data models in Splunk.

    Args:
        app: Specific app to list data models from (default: all apps)

    Returns:
        Dictionary containing list of data models
    """
    service = get_splunk_service()

    try:
        # Get data models in JSON format
        models = service.get('datamodel/model', app=app, owner='-', count=-1, output_mode='json')
        data = json.loads(models.body.read().decode('utf-8'))

        # Extract only essential fields for list operations
        data_models = []
        for entry in data.get('entry', []):
            content = entry.get('content', {})

            # Parse JSON-encoded strings in content
            acceleration_str = content.get('acceleration', '{}')
            description_str = content.get('description', '{}')

            try:
                acceleration = json.loads(acceleration_str) if isinstance(acceleration_str, str) else acceleration_str
            except json.JSONDecodeError:
                acceleration = {}

            try:
                description_data = json.loads(description_str) if isinstance(description_str, str) else description_str
                description = description_data.get('description', '') if isinstance(description_data, dict) else str(description_data)
            except json.JSONDecodeError:
                description = description_str

            data_models.append({
                "name": entry.get('name'),
                "description": description,
                "author": entry.get('author'),
                "updated": entry.get('updated'),
                "app": entry.get('acl', {}).get('app', ''),
                "acceleration_enabled": acceleration.get('enabled', False) if isinstance(acceleration, dict) else False
            })

        return {
            "success": True,
            "data_models": data_models,
            "count": len(data_models)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "data_models": []
        }


@mcp.tool()
def get_data_model(name: str, app: str = "search", summary_only: bool = True) -> dict[str, Any]:
    """
    Get the definition of a specific data model.

    Args:
        name: Name of the data model
        app: App containing the data model (default: search)
        summary_only: Return only summary info to avoid large responses (default: True)

    Returns:
        Dictionary containing data model definition or summary
    """
    service = get_splunk_service()

    try:
        # Get data model in JSON format
        response = service.get(f'datamodel/model/{name}', app=app, owner='nobody', output_mode='json')
        data = json.loads(response.body.read().decode('utf-8'))

        entries = data.get('entry', [])
        if not entries:
            return {
                "success": False,
                "error": f"Data model '{name}' not found"
            }

        entry = entries[0]

        if summary_only:
            # Return summary with key metadata
            content = entry.get('content', {})
            objects = content.get('objects', [])

            # Parse JSON-encoded strings in content
            acceleration_str = content.get('acceleration', '{}')
            description_str = content.get('description', '{}')

            try:
                acceleration = json.loads(acceleration_str) if isinstance(acceleration_str, str) else acceleration_str
            except json.JSONDecodeError:
                acceleration = {}

            try:
                description_data = json.loads(description_str) if isinstance(description_str, str) else description_str
                description = description_data.get('description', '') if isinstance(description_data, dict) else str(description_data)
            except json.JSONDecodeError:
                description = description_str

            return {
                "success": True,
                "data_model_name": name,
                "app": app,
                "acceleration_enabled": acceleration.get('enabled', False) if isinstance(acceleration, dict) else False,
                "description": description,
                "object_count": len(objects),
                "object_names": [obj.get('objectName', '') for obj in objects][:10] if objects else [],
                "note": "Use summary_only=False to get full definition"
            }
        else:
            # Return full entry
            return {
                "success": True,
                "data_model_name": name,
                "data": entry
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def search_data_model(
    datamodel: str,
    object_name: str,
    search_filter: Optional[str] = None,
    earliest_time: str = "-24h",
    latest_time: str = "now",
    max_count: int = 100
) -> dict[str, Any]:
    """
    Execute a tstats search on a data model for accelerated queries.

    This method uses tstats which queries accelerated data model summaries,
    providing significantly faster search performance for large datasets.

    Args:
        datamodel: Name of the data model
        object_name: Name of the object within the data model
        search_filter: Optional filter conditions
        earliest_time: Earliest time for search (default: -24h)
        latest_time: Latest time for search (default: now)
        max_count: Maximum number of results to return (default: 100)

    Returns:
        Dictionary containing search results
    """
    service = get_splunk_service()

    try:
        # Build tstats query
        query = f"| tstats count from datamodel={datamodel}.{object_name}"
        if search_filter:
            query += f" where {search_filter}"

        job = service.jobs.create(
            query,
            earliest_time=earliest_time,
            latest_time=latest_time,
            max_count=max_count
        )

        while not job.is_done():
            pass

        result_stream = job.results(count=max_count)
        reader = results.ResultsReader(result_stream)

        search_results = []
        for result in reader:
            if isinstance(result, dict):
                search_results.append(result)

        job.cancel()

        return {
            "success": True,
            "datamodel": datamodel,
            "object": object_name,
            "results": search_results,
            "result_count": len(search_results)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "results": []
        }


# ============================================================================
# Job Management Tools
# ============================================================================

@mcp.tool()
def list_jobs(count: int = 100) -> dict[str, Any]:
    """
    List recent search jobs.

    Args:
        count: Maximum number of jobs to return (default: 100)

    Returns:
        Dictionary containing list of jobs
    """
    service = get_splunk_service()

    try:
        jobs = []
        for job in service.jobs.list(count=count):
            jobs.append({
                "sid": job.sid,
                "search": job.content.get("search", ""),
                "status": job.content.get("dispatchState", ""),
                "earliest_time": job.content.get("earliestTime", ""),
                "latest_time": job.content.get("latestTime", ""),
                "result_count": job.content.get("resultCount", 0),
                "is_done": job.is_done(),
                "ttl": job.content.get("ttl", "")
            })

        return {
            "success": True,
            "jobs": jobs,
            "count": len(jobs)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "jobs": []
        }


@mcp.tool()
def get_job_results(sid: str, max_count: int = 100) -> dict[str, Any]:
    """
    Get results from a specific search job.

    Args:
        sid: Search ID (SID) of the job
        max_count: Maximum number of results to return (default: 100, 0 = no limit)

    Returns:
        Dictionary containing job results
    """
    service = get_splunk_service()

    try:
        job = service.job(sid)

        # Wait for job to complete if still running
        while not job.is_done():
            pass

        # Get results with pagination for unlimited (max_count=0)
        search_results = []
        if max_count == 0:
            # Paginate through all results
            batch_size = 50000
            offset = 0
            while True:
                result_stream = job.results(count=batch_size, offset=offset)
                reader = results.ResultsReader(result_stream)
                batch = [r for r in reader if isinstance(r, dict)]
                if not batch:
                    break
                search_results.extend(batch)
                offset += len(batch)
                if len(batch) < batch_size:
                    break
        else:
            result_stream = job.results(count=max_count)
            reader = results.ResultsReader(result_stream)
            for result in reader:
                if isinstance(result, dict):
                    search_results.append(result)

        return {
            "success": True,
            "sid": sid,
            "results": search_results,
            "result_count": len(search_results)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "results": []
        }


@mcp.tool()
def cancel_job(sid: str) -> dict[str, Any]:
    """
    Cancel a running search job.

    Args:
        sid: Search ID (SID) of the job to cancel

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        job = service.job(sid)
        job.cancel()

        return {
            "success": True,
            "message": f"Job {sid} cancelled successfully",
            "sid": sid
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# Search Macro Tools
# ============================================================================

@mcp.tool()
def list_macros(app: str = "-") -> dict[str, Any]:
    """
    List all search macros in Splunk.

    Args:
        app: Specific app to list macros from (default: all apps)

    Returns:
        Dictionary containing list of macros with their properties
    """
    service = get_splunk_service()

    try:
        macros = []
        for macro in service.macros:
            # Filter by app if specified
            if app != "-":
                macro_app = macro.access.app if hasattr(macro, 'access') else None
                if macro_app != app:
                    continue

            macros.append({
                "name": macro.name,
                "definition": macro.content.get("definition", ""),
                "args": macro.content.get("args", ""),
                "iseval": macro.content.get("iseval", False),
                "disabled": macro.content.get("disabled", False),
                "app": macro.access.app if hasattr(macro, 'access') else app,
                "sharing": macro.access.sharing if hasattr(macro, 'access') else 'N/A'
            })

        return {
            "success": True,
            "macros": macros,
            "count": len(macros)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "macros": []
        }


@mcp.tool()
def get_macro(name: str, app: str = "search") -> dict[str, Any]:
    """
    Get detailed information about a specific search macro.

    Args:
        name: Name of the macro
        app: App containing the macro (default: search)

    Returns:
        Dictionary containing macro details

    Note:
        If the macro exists in multiple apps, this retrieves the macro
        from the specified app context. Use list_macros() to see all macros
        across apps.
    """
    service = get_splunk_service()

    try:
        # Set namespace to specific app
        service.namespace['app'] = app

        macro = service.macros[name]

        info = {
            "name": macro.name,
            "definition": macro.content.get("definition", ""),
            "args": macro.content.get("args", ""),
            "iseval": macro.content.get("iseval", False),
            "validation": macro.content.get("validation", ""),
            "errormsg": macro.content.get("errormsg", ""),
            "disabled": macro.content.get("disabled", False),
            "app": macro.access.app if hasattr(macro, 'access') else app,
            "author": macro.access.owner if hasattr(macro, 'access') else 'N/A',
            "sharing": macro.access.sharing if hasattr(macro, 'access') else 'N/A'
        }

        return {
            "success": True,
            "macro_info": info
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Macro '{name}' not found in app '{app}'"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_macro(
    name: str,
    definition: str,
    args: Optional[str] = None,
    iseval: bool = False,
    app: str = "search",
    description: Optional[str] = None
) -> dict[str, Any]:
    """
    Create a new search macro in Splunk.

    Args:
        name: Name of the macro
        definition: The macro definition (SPL code)
        args: Comma-separated list of argument names (e.g., "arg1,arg2")
        iseval: Whether the macro is eval-based (default: False)
        app: App to create the macro in (default: search)
        description: Optional description of the macro

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        # Set namespace to specific app
        service.namespace['app'] = app

        # Prepare macro configuration
        kwargs = {"iseval": iseval}
        if args:
            kwargs["args"] = args
        if description:
            kwargs["description"] = description

        # Create the macro
        service.macros.create(name, definition, **kwargs)

        return {
            "success": True,
            "message": f"Macro '{name}' created successfully in app '{app}'",
            "macro_name": name
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def update_macro(
    name: str,
    definition: Optional[str] = None,
    args: Optional[str] = None,
    iseval: Optional[bool] = None,
    disabled: Optional[bool] = None,
    app: str = "search"
) -> dict[str, Any]:
    """
    Update an existing search macro.

    Args:
        name: Name of the macro to update
        definition: Optional new definition
        args: Optional new argument list
        iseval: Optional new iseval setting
        disabled: Optional enable/disable the macro
        app: App containing the macro (default: search)

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        # Set namespace to specific app
        service.namespace['app'] = app

        macro = service.macros[name]

        # Update only provided fields
        update_dict = {}
        if definition is not None:
            update_dict["definition"] = definition
        if args is not None:
            update_dict["args"] = args
        if iseval is not None:
            update_dict["iseval"] = iseval
        if disabled is not None:
            update_dict["disabled"] = disabled

        macro.update(**update_dict).refresh()

        return {
            "success": True,
            "message": f"Macro '{name}' updated successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Macro '{name}' not found in app '{app}'"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_macro(name: str, app: str = "search") -> dict[str, Any]:
    """
    Delete a search macro from Splunk.

    Args:
        name: Name of the macro to delete
        app: App containing the macro (default: search)

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        # Set namespace to specific app
        service.namespace['app'] = app

        macro = service.macros[name]
        macro.delete()

        return {
            "success": True,
            "message": f"Macro '{name}' deleted successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Macro '{name}' not found in app '{app}'"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# Server Message Tools
# ============================================================================

@mcp.tool()
def list_server_messages(severity: Optional[str] = None) -> dict[str, Any]:
    """
    List system messages from Splunk server.

    Args:
        severity: Optional filter by severity (info, warn, error)

    Returns:
        Dictionary containing list of messages
    """
    service = get_splunk_service()

    try:
        messages = []
        for message in service.messages:
            msg_severity = message.content.get("severity", "info")

            # Filter by severity if specified
            if severity and msg_severity != severity:
                continue

            messages.append({
                "name": message.name,
                "value": message.content.get(message.name, ""),
                "severity": msg_severity,
                "timeCreated_iso": message.content.get("timeCreated_iso", ""),
                "timeCreated_epochSecs": message.content.get("timeCreated_epochSecs", "")
            })

        return {
            "success": True,
            "messages": messages,
            "count": len(messages)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "messages": []
        }


@mcp.tool()
def get_server_message(name: str) -> dict[str, Any]:
    """
    Get a specific server message by name.

    Args:
        name: Name of the message

    Returns:
        Dictionary containing message details
    """
    service = get_splunk_service()

    try:
        message = service.messages[name]

        info = {
            "name": message.name,
            "value": message.content.get(message.name, ""),
            "severity": message.content.get("severity", "info"),
            "timeCreated_iso": message.content.get("timeCreated_iso", ""),
            "timeCreated_epochSecs": message.content.get("timeCreated_epochSecs", "")
        }

        return {
            "success": True,
            "message_info": info
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Message '{name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_server_message(
    name: str,
    value: str,
    severity: str = "info"
) -> dict[str, Any]:
    """
    Create a custom server message.

    Args:
        name: Name/key for the message
        value: Message text
        severity: Message severity (info, warn, error) (default: info)

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        service.messages.create(name, value=value, severity=severity)

        return {
            "success": True,
            "message": f"Server message '{name}' created successfully",
            "message_name": name
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_server_message(name: str) -> dict[str, Any]:
    """
    Delete/dismiss a server message.

    Args:
        name: Name of the message to delete

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        message = service.messages[name]
        message.delete()

        return {
            "success": True,
            "message": f"Server message '{name}' deleted successfully"
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Message '{name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# Capabilities Tools
# ============================================================================

@mcp.tool()
def list_system_capabilities() -> dict[str, Any]:
    """
    List all system capabilities available in Splunk.

    Returns:
        Dictionary containing list of all capabilities
    """
    service = get_splunk_service()

    try:
        capabilities = service.capabilities

        return {
            "success": True,
            "capabilities": capabilities,
            "count": len(capabilities)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "capabilities": []
        }


@mcp.tool()
def check_capability(capability_name: str) -> dict[str, Any]:
    """
    Check if a specific capability exists in the system.

    Args:
        capability_name: Name of the capability to check

    Returns:
        Dictionary indicating whether the capability exists
    """
    service = get_splunk_service()

    try:
        capabilities = service.capabilities
        exists = capability_name in capabilities

        return {
            "success": True,
            "capability": capability_name,
            "exists": exists
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def get_role_capabilities(role_name: str) -> dict[str, Any]:
    """
    Get all capabilities assigned to a specific role.

    Args:
        role_name: Name of the role to query

    Returns:
        Dictionary containing capabilities for the role
    """
    service = get_splunk_service()

    try:
        role = service.roles[role_name]

        capabilities = role.content.get("capabilities", [])
        imported_capabilities = role.content.get("imported_capabilities", [])

        return {
            "success": True,
            "role_name": role_name,
            "capabilities": capabilities,
            "imported_capabilities": imported_capabilities,
            "total_capabilities": len(capabilities) + len(imported_capabilities)
        }

    except KeyError:
        return {
            "success": False,
            "error": f"Role '{role_name}' not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# Server Settings Tools
# ============================================================================

@mcp.tool()
def get_server_settings() -> dict[str, Any]:
    """
    Get Splunk server configuration settings.

    Returns:
        Dictionary containing server settings
    """
    service = get_splunk_service()

    try:
        settings = service.settings

        # Extract relevant settings
        settings_data = {
            "SPLUNK_DB": settings.content.get("SPLUNK_DB", ""),
            "SPLUNK_HOME": settings.content.get("SPLUNK_HOME", ""),
            "enableSplunkWebSSL": settings.content.get("enableSplunkWebSSL", False),
            "httpport": settings.content.get("httpport", ""),
            "mgmtHostPort": settings.content.get("mgmtHostPort", ""),
            "minFreeSpace": settings.content.get("minFreeSpace", ""),
            "serverName": settings.content.get("serverName", ""),
            "sessionTimeout": settings.content.get("sessionTimeout", ""),
            "startwebserver": settings.content.get("startwebserver", False),
            "trustedIP": settings.content.get("trustedIP", "")
        }

        return {
            "success": True,
            "settings": settings_data
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def update_server_settings(**kwargs) -> dict[str, Any]:
    """
    Update Splunk server configuration settings.

    Args:
        **kwargs: Settings to update. Common settings include:
            - sessionTimeout: Session timeout in seconds
            - startwebserver: Boolean to enable/disable Splunk Web
            - httpport: Splunk Web port number
            - mgmtHostPort: Management port (format: "host:port")
            - trustedIP: Comma-separated list of trusted IP addresses

    Returns:
        Dictionary indicating success or failure

    Note:
        See Splunk server.conf documentation for complete list of available settings.
    """
    service = get_splunk_service()

    try:
        settings = service.settings
        settings.update(**kwargs)

        return {
            "success": True,
            "message": "Server settings updated successfully",
            "updated_fields": list(kwargs.keys())
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def check_restart_required() -> dict[str, Any]:
    """
    Check if Splunk server requires a restart.

    Returns:
        Dictionary indicating whether a restart is required
    """
    service = get_splunk_service()

    try:
        restart_required = service.restart_required

        return {
            "success": True,
            "restart_required": restart_required
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def restart_splunk() -> dict[str, Any]:
    """
    Restart the Splunk server.

    WARNING: This will restart the Splunk instance, causing temporary unavailability.

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        service.restart()

        return {
            "success": True,
            "message": "Splunk restart initiated. The server will be unavailable briefly."
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def refresh_splunk() -> dict[str, Any]:
    """
    Refresh Splunk configuration without a full restart.

    This reloads configuration files and refreshes the Python interpreter,
    which is faster than a full restart and doesn't cause service interruption.

    Returns:
        Dictionary indicating success or failure
    """
    service = get_splunk_service()

    try:
        # Reload apps and configurations
        service.post("/services/apps/local/_reload")

        return {
            "success": True,
            "message": "Splunk configuration refreshed successfully"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def main():
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
