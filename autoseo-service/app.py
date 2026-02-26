from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import uuid
from typing import Optional, List, Dict
import sqlite3
import json

from crawler import Crawler
from analyzer import SEOAnalyzer
from models import init_db, execute_query
from auth import verify_api_key, generate_api_key

app = FastAPI(title="AutoSEO Service - Multi-Tenant")

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

class TenantResponse(BaseModel):
    id: str
    name: str
    email: str
    api_key: str
    created_at: str

# Dependency to get tenant from API key
async def get_tenant(api_key: str = Header(..., alias="X-API-Key")):
    tenant = verify_api_key(api_key)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return tenant

# Public endpoints
@app.post("/tenants", response_model=TenantResponse)
async def create_tenant(tenant: TenantRequest):
    """Register a new tenant (client)"""
    tenant_id = str(uuid.uuid4())
    api_key = generate_api_key()
    
    execute_query(
        "INSERT INTO tenants (id, name, email, api_key, created_at) VALUES (?, ?, ?, ?, ?)",
        (tenant_id, tenant.name, tenant.email, api_key, datetime.now().isoformat())
    )
    
    return {
        "id": tenant_id,
        "name": tenant.name,
        "email": tenant.email,
        "api_key": api_key,
        "created_at": datetime.now().isoformat()
    }

# Protected endpoints (require API key)
@app.post("/sites", response_model=SiteResponse)
async def add_site(
    site: SiteRequest, 
    background_tasks: BackgroundTasks,
    tenant: dict = Depends(get_tenant)
):
    """Add a new site for SEO monitoring"""
    site_id = str(uuid.uuid4())
    
    execute_query(
        """INSERT INTO sites (id, tenant_id, url, name, settings, created_at, status) 
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (site_id, tenant['id'], site.url, site.name or site.url, 
         json.dumps(site.settings), datetime.now().isoformat(), 'pending')
    )
    
    # Start audit in background
    background_tasks.add_task(run_audit, site_id, site.url, tenant['id'])
    
    return {
        "id": site_id,
        "url": site.url,
        "name": site.name or site.url,
        "tenant_id": tenant['id'],
        "created_at": datetime.now().isoformat(),
        "status": "pending",
        "last_score": None,
        "last_audit": None
    }

@app.get("/sites", response_model=List[SiteResponse])
async def list_sites(tenant: dict = Depends(get_tenant)):
    """List all sites for this tenant"""
    results = execute_query(
        "SELECT id, url, name, tenant_id, created_at, status, last_score, last_audit FROM sites WHERE tenant_id = ? ORDER BY created_at DESC",
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
        "last_audit": r[7]
    } for r in results]

@app.get("/sites/{site_id}", response_model=SiteResponse)
async def get_site(site_id: str, tenant: dict = Depends(get_tenant)):
    """Get site details"""
    results = execute_query(
        "SELECT id, url, name, tenant_id, created_at, status, last_score, last_audit FROM sites WHERE id = ? AND tenant_id = ?",
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
        "last_audit": r[7]
    }

@app.get("/sites/{site_id}/audits", response_model=List[AuditResponse])
async def get_site_audits(site_id: str, tenant: dict = Depends(get_tenant)):
    """Get all audits for a site"""
    # Verify site belongs to tenant
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
    """Manually trigger an audit"""
    site = execute_query(
        "SELECT url FROM sites WHERE id = ? AND tenant_id = ?",
        (site_id, tenant['id']),
        fetch=True
    )
    
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    background_tasks.add_task(run_audit, site_id, site[0][0], tenant['id'])
    
    return {"message": "Audit started", "site_id": site_id}

@app.get("/dashboard")
async def get_dashboard(tenant: dict = Depends(get_tenant)):
    """Get dashboard summary for tenant"""
    # Get site count
    sites = execute_query(
        "SELECT COUNT(*) FROM sites WHERE tenant_id = ?",
        (tenant['id'],),
        fetch=True
    )
    
    # Get average score
    avg_score = execute_query(
        """SELECT AVG(score) FROM audits a 
           JOIN sites s ON a.site_id = s.id 
           WHERE s.tenant_id = ?""",
        (tenant['id'],),
        fetch=True
    )
    
    # Get recent audits
    recent = execute_query(
        """SELECT s.name, a.score, a.created_at 
           FROM audits a 
           JOIN sites s ON a.site_id = s.id 
           WHERE s.tenant_id = ? 
           ORDER BY a.created_at DESC LIMIT 5""",
        (tenant['id'],),
        fetch=True
    )
    
    return {
        "tenant": tenant['name'],
        "total_sites": sites[0][0] if sites else 0,
        "average_score": round(avg_score[0][0], 2) if avg_score and avg_score[0][0] else 0,
        "recent_audits": [{
            "site": r[0],
            "score": r[1],
            "date": r[2]
        } for r in recent]
    }

# Background task
def run_audit(site_id: str, url: str, tenant_id: str):
    """Run SEO audit in background"""
    try:
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
        execute_query(
            """INSERT INTO audits (id, site_id, score, issues, pages_analyzed, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (audit_id, site_id, analysis['score'], 
             json.dumps(analysis['issues']), len(pages), 
             datetime.now().isoformat())
        )
        
        # Update site
        execute_query(
            """UPDATE sites 
               SET status = 'completed', last_audit = ?, last_score = ? 
               WHERE id = ?""",
            (audit_id, analysis['score'], site_id)
        )
        
    except Exception as e:
        execute_query(
            "UPDATE sites SET status = 'failed' WHERE id = ?",
            (site_id,)
        )
        print(f"Audit failed for tenant {tenant_id}, site {site_id}: {e}")

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "AutoSEO Multi-Tenant"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
