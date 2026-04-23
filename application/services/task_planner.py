from __future__ import annotations

from connectors.base.base_connector import BaseConnector

class TaskPlanner:
    def __init__(self, connector: BaseConnector) -> None:
        self.connector = connector

    def plan(self, requirement):
        return self.connector.plan_requirement(requirement)
