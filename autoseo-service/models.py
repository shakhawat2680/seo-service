import sqlite3
from typing import List, Any, Optional
from datetime import datetime, timedelta

DB_PATH = 'autoseo.db'

def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with multi-tenant support and usage tracking"""
    conn = get_connection()
    c = conn.cursor()
    
    # Tenants table with usage tracking
    c.execute('''
        CREATE TABLE IF NOT EXISTS tenants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            api_key TEXT UNIQUE,
            plan_type TEXT DEFAULT 'free',
            usage_count INTEGER DEFAULT 0,
            rate_limit INTEGER DEFAULT 100,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            settings TEXT DEFAULT '{}'
        )
    ''')
    
    # Sites table
    c.execute('''
        CREATE TABLE IF NOT EXISTS sites (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            url TEXT NOT NULL,
            name TEXT NOT NULL,
            settings TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            last_audit TEXT,
            last_score REAL,
            audit_count INTEGER DEFAULT 0,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id),
            UNIQUE(tenant_id, url)
        )
    ''')
    
    # Audits table
    c.execute('''
        CREATE TABLE IF NOT EXISTS audits (
            id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            score REAL NOT NULL,
            issues TEXT NOT NULL,
            pages_analyzed INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (site_id) REFERENCES sites (id),
            FOREIGN KEY (tenant_id) REFERENCES tenants (id)
        )
    ''')
    
    # Usage logs for detailed tracking
    c.execute('''
        CREATE TABLE IF NOT EXISTS usage_logs (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            action TEXT NOT NULL,
            resource TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id)
        )
    ''')
    
    # Indexes
    c.execute('CREATE INDEX IF NOT EXISTS idx_tenants_api_key ON tenants(api_key)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_tenants_plan ON tenants(plan_type)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_sites_tenant ON sites(tenant_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_audits_tenant ON audits(tenant_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_audits_site ON audits(site_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_usage_tenant ON usage_logs(tenant_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_usage_time ON usage_logs(timestamp)')
    
    conn.commit()
    conn.close()

def execute_query(query: str, params: tuple = (), fetch: bool = False) -> List[Any]:
    """Execute query with automatic connection handling"""
    conn = get_connection()
    c = conn.cursor()
    
    try:
        c.execute(query, params)
        
        if fetch:
            results = c.fetchall()
            conn.commit()
            return [tuple(r) for r in results]
        else:
            conn.commit()
            return []
            
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_tenant(tenant_id: str) -> Optional[dict]:
    """Get tenant by ID"""
    results = execute_query(
        "SELECT id, name, email, plan_type, usage_count, rate_limit, created_at FROM tenants WHERE id = ?",
        (tenant_id,),
        fetch=True
    )
    
    if results:
        r = results[0]
        return {
            'id': r[0],
            'name': r[1],
            'email': r[2],
            'plan_type': r[3],
            'usage_count': r[4],
            'rate_limit': r[5],
            'created_at': r[6]
        }
    return None

def get_tenant_by_api_key(api_key_hash: str) -> Optional[dict]:
    """Get tenant by API key hash"""
    results = execute_query(
        "SELECT id, name, email, plan_type, usage_count, rate_limit, created_at FROM tenants WHERE api_key = ?",
        (api_key_hash,),
        fetch=True
    )
    
    if results:
        r = results[0]
        return {
            'id': r[0],
            'name': r[1],
            'email': r[2],
            'plan_type': r[3],
            'usage_count': r[4],
            'rate_limit': r[5],
            'created_at': r[6]
        }
    return None

def increment_usage(tenant_id: str):
    """Increment usage count for tenant"""
    execute_query(
        "UPDATE tenants SET usage_count = usage_count + 1, updated_at = ? WHERE id = ?",
        (datetime.now().isoformat(), tenant_id)
    )

def check_rate_limit(tenant_id: str) -> bool:
    """Check if tenant has exceeded rate limit"""
    # Get current period usage (last 24 hours)
    yesterday = (datetime.now() - timedelta(days=1)).isoformat()
    
    results = execute_query(
        "SELECT COUNT(*) FROM usage_logs WHERE tenant_id = ? AND timestamp > ?",
        (tenant_id, yesterday),
        fetch=True
    )
    
    current_usage = results[0][0] if results else 0
    
    # Get tenant's rate limit
    tenant = get_tenant(tenant_id)
    if not tenant:
        return False
    
    return current_usage < tenant['rate_limit']

def log_usage(tenant_id: str, action: str, resource: str = None):
    """Log usage action"""
    import uuid
    log_id = str(uuid.uuid4())
    
    execute_query(
        "INSERT INTO usage_logs (id, tenant_id, action, resource, timestamp) VALUES (?, ?, ?, ?, ?)",
        (log_id, tenant_id, action, resource, datetime.now().isoformat())
    )

def reset_usage_counts():
    """Reset usage counts (can be run via cron)"""
    execute_query("UPDATE tenants SET usage_count = 0")
    execute_query("DELETE FROM usage_logs WHERE timestamp < ?", 
                  ((datetime.now() - timedelta(days=30)).isoformat(),))

def get_tenant_stats(tenant_id: str) -> dict:
    """Get usage statistics for tenant"""
    # Total sites
    sites = execute_query(
        "SELECT COUNT(*) FROM sites WHERE tenant_id = ?",
        (tenant_id,),
        fetch=True
    )
    
    # Total audits
    audits = execute_query(
        "SELECT COUNT(*) FROM audits WHERE tenant_id = ?",
        (tenant_id,),
        fetch=True
    )
    
    # Usage this month
    month_start = datetime.now().replace(day=1).isoformat()
    monthly_usage = execute_query(
        "SELECT COUNT(*) FROM usage_logs WHERE tenant_id = ? AND timestamp > ?",
        (tenant_id, month_start),
        fetch=True
    )
    
    # Last 7 days activity
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    weekly_activity = execute_query(
        "SELECT DATE(timestamp) as day, COUNT(*) FROM usage_logs WHERE tenant_id = ? AND timestamp > ? GROUP BY DATE(timestamp)",
        (tenant_id, week_ago),
        fetch=True
    )
    
    return {
        'total_sites': sites[0][0] if sites else 0,
        'total_audits': audits[0][0] if audits else 0,
        'monthly_usage': monthly_usage[0][0] if monthly_usage else 0,
        'weekly_activity': [{'date': r[0], 'count': r[1]} for r in weekly_activity]
    }

def update_tenant_plan(tenant_id: str, plan_type: str, rate_limit: int):
    """Update tenant plan and rate limit"""
    execute_query(
        "UPDATE tenants SET plan_type = ?, rate_limit = ?, updated_at = ? WHERE id = ?",
        (plan_type, rate_limit, datetime.now().isoformat(), tenant_id)
    )
