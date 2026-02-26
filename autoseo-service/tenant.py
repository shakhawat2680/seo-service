class Tenant:
    def __init__(self, name, plan="free", limit=100):
        self.name = name
        self.plan = plan
        self.limit = limit
        self.usage = 0

    def can_use(self):
        return self.usage < self.limit

    def track_usage(self):
        self.usage += 1
