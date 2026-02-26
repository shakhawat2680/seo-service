from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import uuid
from typing import Optional, List, Dict
import json

from crawler import Crawler
from analyzer import SEOAnalyzer
from models import (
    init_db, execute_query, get_tenant, get_tenant_stats, 
    update_tenant_plan, get_cycle_usage, calculate_overage_charges,
    initialize_tenant_billing, check_and_reset_usage
)
from auth import verify_api_key, generate_api_key, log_usage

app = FastAPI(title="AutoSEO Service - Multi-Tenant with Billing")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database
init_db()

# Models
class SiteRequest(BaseModel):
    url: str
    name: Optional[str] = None
    settings: Optional[Dict] = {}

class SiteResponse(BaseModel):
    id: str
    url: str
    name: str
    tenant_id: str
    created_at: str
    status: str
    last_score: Optional[float]
    last_audit: Optional[str]
    audit_count: Optional[int]

class AuditResponse(BaseModel):
    id: str
    site_id: str
    score: float
    issues: List[dict]
    pages_analyzed: int
    created_at: str

class TenantRequest(BaseModel):
    name: str
    email: str
    plan_type: str = "free"
    billing_cycle: str = "monthly"  # monthly, yearly

class TenantResponse(BaseModel):
    id: str
    name: str
    email: str
    plan_type: str
    billing_cycle: str
    usage_count: int
    rate_limit: int
    api_key: str
    created_at: str
    billing_start: Optional[str]
    billing_end: Optional[str]
    subscription_status: str

class PlanUpdateRequest(BaseModel):
    plan_type: str
    billing_cycle: Optional[str] = None

class UsageResponse(BaseModel):
    tenant_id: str
    plan_type: str
    billing_cycle: str
    billing_start: str
    billing_end: str
    days_left: int
    current_usage: int
    rate_limit: int
    remaining: int
    percentage_used: float
    total_sites: int
    total_audits: int
    estimated_overage: Optional[dict]

class BillingHistoryResponse(BaseModel):
    cycle: str
    usage: int
    limit: int
    overage: int
    overage_charge: float
    status: str
    payment_date: Optional[str]

# Dependency with enhanced error handling
async def get_tenant(api_key: str = Header(..., alias="X-API-Key")):
    result = verify_api_key(api_key)
    
    if not result:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if isinstance(result, dict) and 'error' in result:
        error = result['error']
        rate_info = result.get('rate_info', {})
        
        if error == 'subscription_inactive':
            raise HTTPException(
                status_code=402,  # Payment Required
                detail={
                    "error": "subscription_inactive",
                    "message": "Your subscription is inactive. Please update payment method.",
                    "status": rate_info.get('status')
                }
            )
        else:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": rate_info.get('message', 'Rate limit exceeded'),
                    "current_usage": rate_info.get('current_usage'),
                    "limit": rate_info.get('limit'),
                    "remaining": 0,
                    "days_left": rate_info.get('days_left'),
                    "billing_end": rate_info.get('billing_end')
                }
            )
    
    return result

# Public endpoints
@app.post("/tenants", response_model=TenantResponse)
async def create_tenant(tenant: TenantRequest):
    """Register a new tenant (client)"""
    tenant_id = str(uuid.uuid4())
    api_key = generate_api_key()
    
    # Get plan rate limit
    plan = execute_query(
        "SELECT rate_limit FROM plans WHERE id = ?",
        (tenant.plan_type,),
        fetch=True
    )
    rate_limit = plan[0][0] if plan else 100
    
    execute_query(
        """INSERT INTO tenants (
            id, name, email, api_key, plan_type, billing_cycle, 
            rate_limit, created_at, subscription_status
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (tenant_id, tenant.name, tenant.email, api_key, tenant.plan_type, 
         tenant.billing_cycle, rate_limit, datetime.now().isoformat(), 'active')
    )
    
    # Initialize billing
    from models import initialize_tenant_billing
    initialize_tenant_billing(tenant_id, tenant.plan_type, tenant.billing_cycle)
    
    # Get complete tenant data
    result = get_tenant(tenant_id)
    
    return {
        "id": result['id'],
        "name": result['name'],
        "email": result['email'],
        "plan_type": result['plan_type'],
        "billing_cycle": result['billing_cycle'],
        "usage_count": result['usage_count'],
        "rate_limit": result['rate_limit'],
        "api_key": api_key,
        "created_at": result['created_at'],
        "billing_start": result['billing_start'],
        "billing_end": result['billing_end'],
        "subscription_status": result['subscription_status']
    }

# Protected endpoints
@app.post("/sites", response_model=SiteResponse)
async def add_site(
    site: SiteRequest, 
    background_tasks: BackgroundTasks,
    tenant: dict = Depends(get_tenant)
):
    """Add a new site for SEO monitoring"""
    site_id = str(uuid.uuid4())
    
    # Check if site already exists
    existing = execute_query(
        "SELECT id FROM sites WHERE tenant_id = ? AND url = ?",
        (tenant['id'], site.url),
        fetch=True
    )
    
    if existing:
        raise HTTPException(status_code=400, detail="Site already exists")
    
    execute_query(
        """INSERT INTO sites (id, tenant_id, url, name, settings, created_at, status, audit_count) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (site_id, tenant['id'], site.url, site.name or site.url, 
         json.dumps(site.settings), datetime.now().isoformat(), 'pending', 0)
    )
    
    # Log usage
    log_usage(tenant['id'], 'add_site', site_id)
    
    # Start audit
    background_tasks.add_task(run_audit, site_id, site.url, tenant['id'])
    
    return {
        "id": site_id,
        "url": site.url,
        "name": site.name or site.url,
        "tenant_id": tenant['id'],
        "created_at": datetime.now().isoformat(),
        "status": "pending",
        "last_score": None,
        "last_audit": None,
        "audit_count": 0
    }

@app.get("/usage", response_model=UsageResponse)
async def get_usage(tenant: dict = Depends(get_tenant)):
    """Get detailed usage with billing info"""
    from models import get_tenant_stats, calculate_overage_charges
    
    stats = get_tenant_stats(tenant['id'])
    billing_end = datetime.fromisoformat(tenant['billing_end'])
    days_left = (billing_end - datetime.now()).days
    percentage_used = (tenant['usage_count'] / tenant['rate_limit'] * 100) if tenant['rate_limit'] > 0 else 0
    
    # Calculate potential overage
    overage = None
    if tenant['usage_count'] > tenant['rate_limit'] * 0.8:  # Show estimate if >80% used
        overage = calculate_overage_charges(tenant['id'])
    
    return {
        "tenant_id": tenant['id'],
        "plan_type": tenant['plan_type'],
        "billing_cycle": tenant['billing_cycle'],
        "billing_start": tenant['billing_start'],
        "billing_end": tenant['billing_end'],
        "days_left": max(0, days_left),
        "current_usage": tenant['usage_count'],
        "rate_limit": tenant['rate_limit'],
        "remaining": max(0, tenant['rate_limit'] - tenant['usage_count']),
        "percentage_used": round(percentage_used, 2),
        "total_sites": stats['total_sites'],
        "total_audits": stats['total_audits'],
        "estimated_overage": overage if overage and overage['overage'] > 0 else None
    }

@app.get("/billing/history", response_model=List[BillingHistoryResponse])
async def get_billing_history(tenant: dict = Depends(get_tenant)):
    """Get billing history for tenant"""
    history = execute_query(
        """SELECT cycle_start, cycle_end, usage, overage, status, payment_date 
           FROM billing_history 
           WHERE tenant_id = ? 
           ORDER BY created_at DESC""",
        (tenant['id'],),
        fetch=True
    )
    
    result = []
    for h in history:
        # Get plan overage rate
        plan = execute_query(
            "SELECT overage_rate FROM plans WHERE id = ?",
            (tenant['plan_type'],),
            fetch=True
        )
        overage_rate = plan[0][0] if plan else 0
        overage_charge = (h[3] * overage_rate / 100) if h[3] > 0 else 0
        
        result.append({
            "cycle": f"{h[0][:7]} to {h[1][:7]}",
            "usage": h[2],
            "limit": tenant['rate_limit'],
            "overage": h[3],
            "overage_charge": overage_charge,
            "status": h[4],
            "payment_date": h[5]
        })
    
    return result

@app.post("/tenants/{tenant_id}/plan")
async def update_plan(
    tenant_id: str, 
    plan: PlanUpdateRequest,
    admin_key: str = Header(...)
):
    """Update tenant plan (admin only)"""
    if admin_key != "admin_secret_key":
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    success = update_tenant_plan(tenant_id, plan.plan_type, plan.billing_cycle)
    
    if not success:
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    # Reset billing cycle if changed
    if plan.billing_cycle:
        from models import initialize_tenant_billing
        initialize_tenant_billing(tenant_id, plan.plan_type, plan.billing_cycle)
    
    return {"message": "Plan updated", "tenant_id": tenant_id, "plan": plan.plan_type}

@app.post("/billing/reset")
async def manual_reset(admin_key: str = Header(...)):
    """Manually reset all billing cycles (admin only - for testing)"""
    if admin_key != "admin_secret_key":
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    from models import check_and_reset_usage
    
    # Get all tenants
    tenants = execute_query("SELECT id FROM tenants", fetch=True)
    
    for tenant in tenants:
        check_and_reset_usage(tenant[0])
    
    return {"message": f"Reset {len(tenants)} tenants"}

# Background task (updated)
def run_audit(site_id: str, url: str, tenant_id: str):
    """Run SEO audit in background"""
    try:
        # Check usage before proceeding
        from models import check_rate_limit
        allowed, _ = check_rate_limit(tenant_id)
        
        if not allowed:
            execute_query(
                "UPDATE sites SET status = 'failed' WHERE id = ?",
                (site_id,)
            )
            return
        
        # Update status
        execute_query(
            "UPDATE sites SET status = 'running' WHERE id = ?",
            (site_id,)
        )
        
        # Crawl site
        crawler = Crawler()
        pages = crawler.crawl(url, max_pages=50)
        
        # Analyze
        analyzer = SEOAnalyzer()
        analysis = analyzer.analyze(pages)
        
        # Save audit
        audit_id = str(uuid.uuid4())
        current_cycle = datetime.now().strftime('%Y-%m')
        
        execute_query(
            """INSERT INTO audits (id, site_id, tenant_id, score, issues, pages_analyzed, created_at, billing_cycle)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (audit_id, site_id, tenant_id, analysis['score'], 
             json.dumps(analysis['issues']), len(pages), 
             datetime.now().isoformat(), current_cycle)
        )
        
        # Update site
        execute_query(
            """UPDATE sites 
               SET status = 'completed', last_audit = ?, last_score = ?, 
                   audit_count = IFNULL(audit_count, 0) + 1
               WHERE id = ?""",
            (audit_id, analysis['score'], site_id)
        )
        
        # Log usage
        log_usage(tenant_id, 'audit_completed', audit_id)
        
    except Exception as e:
        execute_query(
            "UPDATE sites SET status = 'failed' WHERE id = ?",
            (site_id,)
        )
        print(f"Audit failed for tenant {tenant_id}, site {site_id}: {e}")

# Keep existing endpoints
@app.get("/sites", response_model=List[SiteResponse])
async def list_sites(tenant: dict = Depends(get_tenant)):
    results = execute_query(
        """SELECT id, url, name, tenant_id, created_at, status, last_score, last_audit, audit_count 
           FROM sites WHERE tenant_id = ? ORDER BY created_at DESC""",
        (tenant['id'],),
        fetch=True
    )
    
    return [{
        "id": r[0],
        "url": r[1],
        "name": r[2],
        "tenant_id": r[3],
        "created_at": r[4],
        "status": r[5],
        "last_score": r[6],
        "last_audit": r[7],
        "audit_count": r[8] or 0
    } for r in results]

@app.get("/sites/{site_id}", response_model=SiteResponse)
async def get_site(site_id: str, tenant: dict = Depends(get_tenant)):
    results = execute_query(
        "SELECT id, url, name, tenant_id, created_at, status, last_score, last_audit, audit_count FROM sites WHERE id = ? AND tenant_id = ?",
        (site_id, tenant['id']),
        fetch=True
    )
    
    if not results:
        raise HTTPException(status_code=404, detail="Site not found")
    
    r = results[0]
    return {
        "id": r[0],
        "url": r[1],
        "name": r[2],
        "tenant_id": r[3],
        "created_at": r[4],
        "status": r[5],
        "last_score": r[6],
        "last_audit": r[7],
        "audit_count": r[8] or 0
    }

@app.get("/sites/{site_id}/audits", response_model=List[AuditResponse])
async def get_site_audits(site_id: str, tenant: dict = Depends(get_tenant)):
    site = execute_query(
        "SELECT id FROM sites WHERE id = ? AND tenant_id = ?",
        (site_id, tenant['id']),
        fetch=True
    )
    
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    results = execute_query(
        """SELECT id, site_id, score, issues, pages_analyzed, created_at 
           FROM audits WHERE site_id = ? ORDER BY created_at DESC""",
        (site_id,),
        fetch=True
    )
    
    return [{
        "id": r[0],
        "site_id": r[1],
        "score": r[2],
        "issues": json.loads(r[3]),
        "pages_analyzed": r[4],
        "created_at": r[5]
    } for r in results]

@app.post("/sites/{site_id}/audit")
async def trigger_audit(
    site_id: str, 
    background_tasks: BackgroundTasks,
    tenant: dict = Depends(get_tenant)
):
    site = execute_query(
        "SELECT url, audit_count FROM sites WHERE id = ? AND tenant_id = ?",
        (site_id, tenant['id']),
        fetch=True
    )
    
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    log_usage(tenant['id'], 'trigger_audit', site_id)
    background_tasks.add_task(run_audit, site_id, site[0][0], tenant['id'])
    
    return {"message": "Audit started", "site_id": site_id}

@app.get("/dashboard")
async def get_dashboard(tenant: dict = Depends(get_tenant)):
    sites = execute_query(
        "SELECT COUNT(*) FROM sites WHERE tenant_id = ?",
        (tenant['id'],),
        fetch=True
    )
    
    avg_score = execute_query(
        """SELECT AVG(score) FROM audits a 
           JOIN sites s ON a.site_id = s.id 
           WHERE s.tenant_id = ?""",
        (tenant['id'],),
        fetch=True
    )
    
    recent = execute_query(
        """SELECT s.name, a.score, a.created_at 
           FROM audits a 
           JOIN sites s ON a.site_id = s.id 
           WHERE s.tenant_id = ? 
           ORDER BY a.created_at DESC LIMIT 5""",
        (tenant['id'],),
        fetch=True
    )
    
    # Calculate days left in billing cycle
    billing_end = datetime.fromisoformat(tenant['billing_end'])
    days_left = (billing_end - datetime.now()).days
    
    return {
        "tenant": tenant['name'],
        "plan": tenant['plan_type'],
        "billing": {
            "cycle": tenant['billing_cycle'],
            "billing_end": tenant['billing_end'],
            "days_left": max(0, days_left)
        },
        "usage": {
            "current": tenant['usage_count'],
            "limit": tenant['rate_limit'],
            "remaining": max(0, tenant['rate_limit'] - tenant['usage_count']),
            "percentage": round(tenant['usage_count'] / tenant['rate_limit'] * 100, 2) if tenant['rate_limit'] > 0 else 0
        },
        "total_sites": sites[0][0] if sites else 0,
        "average_score": round(avg_score[0][0], 2) if avg_score and avg_score[0][0] else 0,
        "recent_audits": [{
            "site": r[0],
            "score": r[1],
            "date": r[2]
        } for r in recent]
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "AutoSEO Multi-Tenant with Billing"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
