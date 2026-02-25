import os
from google.analytics.admin import AnalyticsAdminServiceClient
from google.analytics.data import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest, 
    RunRealtimeReportRequest,
    DateRange, 
    Metric, 
    Dimension,
    FilterExpression,
    Filter
)

# --- TOOLS IMPLEMENTATION ---

def get_account_summaries(creds):
    """Retrieves accessable accounts and properties."""
    try:
        client = AnalyticsAdminServiceClient(credentials=creds)
        summaries = []
        for account in client.list_account_summaries():
            acc_data = {
                "account_name": account.account, # properties/xxx/accountSummaries/yyy ? No, format is accountSummaries/xxx
                "display_name": account.display_name,
                "properties": []
            }
            for prop in account.property_summaries:
                acc_data["properties"].append({
                    "property_id": prop.property, # format: properties/123
                    "display_name": prop.display_name
                })
            summaries.append(acc_data)
        return summaries
    except Exception as e:
        return {"error": str(e), "error_type": type(e).__name__}

def get_property_details(property_id, creds):
    """Returns details about a property."""
    try:
        client = AnalyticsAdminServiceClient(credentials=creds)
        # Note: property_id should be 'properties/123456'
        # Check format
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"
            
        repo = client.get_property(name=property_id)
        return {
            "name": repo.name,
            "display_name": repo.display_name,
            "create_time": str(repo.create_time),
            "update_time": str(repo.update_time),
            "industry_category": repo.industry_category.name,
            "time_zone": repo.time_zone
        }
    except Exception as e:
        return {"error": str(e), "error_type": type(e).__name__}

def list_google_ads_links(property_id, creds):
    """Lists Google Ads links for a property."""
    try:
        client = AnalyticsAdminServiceClient(credentials=creds)
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"
            
        links = []
        for link in client.list_google_ads_links(parent=property_id):
            links.append({
                "name": link.name,
                "customer_id": link.customer_id,
                "email_address": link.creator_email_address
            })
        return links
    except Exception as e:
        return {"error": str(e), "error_type": type(e).__name__}

def run_report(property_id, dimensions, metrics, date_ranges, creds, limit=10):
    """Runs a standard GA4 report."""
    try:
        client = BetaAnalyticsDataClient(credentials=creds)
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"

        # Prepare request objects
        dim_objs = [Dimension(name=d) for d in dimensions]
        met_objs = [Metric(name=m) for m in metrics]
        date_objs = [DateRange(start_date=dr['start_date'], end_date=dr['end_date']) for dr in date_ranges]

        request = RunReportRequest(
            property=property_id,
            dimensions=dim_objs,
            metrics=met_objs,
            date_ranges=date_objs,
            limit=limit
        )
        
        response = client.run_report(request)
        
        # Format output as list of dicts
        result = []
        for row in response.rows:
            item = {}
            for i, d_val in enumerate(row.dimension_values):
                item[dimensions[i]] = d_val.value
            for i, m_val in enumerate(row.metric_values):
                item[metrics[i]] = m_val.value
            result.append(item)
            
        return result
    except Exception as e:
        return {"error": str(e), "error_type": type(e).__name__}

def run_realtime_report(property_id, dimensions, metrics, creds, limit=10):
    """Runs a realtime GA4 report."""
    try:
        client = BetaAnalyticsDataClient(credentials=creds)
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"

        dim_objs = [Dimension(name=d) for d in dimensions]
        met_objs = [Metric(name=m) for m in metrics]

        request = RunRealtimeReportRequest(
            property=property_id,
            dimensions=dim_objs,
            metrics=met_objs,
            limit=limit
        )
        
        response = client.run_realtime_report(request)
        
        result = []
        for row in response.rows:
            item = {}
            for i, d_val in enumerate(row.dimension_values):
                item[dimensions[i]] = d_val.value
            for i, m_val in enumerate(row.metric_values):
                item[metrics[i]] = m_val.value
            result.append(item)
            
        return result
    except Exception as e:
        return {"error": str(e), "error_type": type(e).__name__}
