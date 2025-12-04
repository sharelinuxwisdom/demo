#!/usr/bin/env python3
import requests
import json
import threading
import time
import queue

class GrafanaMCPClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        self.sse_url = f"{base_url}/sse"
        self.session_id = None
        self.message_url = None
        self.responses = {}
        self.event_queue = queue.Queue()
        self.stop_listening = False
        
    def _sse_listener(self):
        """Background thread to listen for SSE events"""
        try:
            response = requests.get(
                self.sse_url,
                headers={"Accept": "text/event-stream"},
                stream=True
            )
            
            current_event = None
            current_data = []
            
            for line in response.iter_lines(decode_unicode=True):
                if self.stop_listening:
                    break
                    
                if not line:
                    if current_event and current_data:
                        data_str = '\n'.join(current_data)
                        self._handle_event(current_event, data_str)
                        current_event = None
                        current_data = []
                    continue
                
                if line.startswith('event: '):
                    current_event = line[7:].strip()
                elif line.startswith('data: '):
                    current_data.append(line[6:])
                    
        except Exception as e:
            print(f"SSE listener error: {e}")
    
    def _handle_event(self, event_type, data):
        """Handle incoming SSE events"""
        if event_type == 'endpoint':
            if 'sessionId=' in data:
                self.session_id = data.split('sessionId=')[1].strip()
                self.message_url = f"{self.base_url}{data.strip()}"
                print(f"✓ Session established: {self.session_id}")
        
        elif event_type == 'message':
            try:
                json_data = json.loads(data)
                request_id = json_data.get('id')
                
                if request_id:
                    self.responses[request_id] = json_data
                else:
                    self.event_queue.put(json_data)
                    
            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON: {e}")
    
    def connect(self):
        """Start SSE connection and wait for session ID"""
        print("Starting SSE listener...")
        listener = threading.Thread(target=self._sse_listener, daemon=True)
        listener.start()
        
        timeout = 10
        start_time = time.time()
        while not self.session_id:
            if time.time() - start_time > timeout:
                raise TimeoutError("Failed to get session ID")
            time.sleep(0.1)
        
        print(f"✓ Connected!\n")
        return self.session_id
    
    def send_request(self, method, params=None, timeout=30):
        """Send request and wait for response"""
        if not self.message_url:
            raise Exception("Not connected")
        
        request_id = int(time.time() * 1000000)
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {}
        }
        
        response = requests.post(
            self.message_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 202:
            start_time = time.time()
            while request_id not in self.responses:
                if time.time() - start_time > timeout:
                    raise TimeoutError(f"No response within {timeout}s")
                time.sleep(0.1)
            
            return self.responses[request_id]
            
        elif response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Request failed: {response.status_code} - {response.text}")
    
    def call_tool(self, tool_name, arguments, timeout=30):
        """Call a specific tool"""
        return self.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        }, timeout=timeout)
    
    def extract_result_text(self, response):
        """Helper to extract text from MCP response"""
        if 'result' in response and 'content' in response['result']:
            for item in response['result']['content']:
                if item.get('type') == 'text':
                    try:
                        text = item.get('text', '')
                        # Try to parse as JSON if it looks like JSON
                        if text.startswith('[') or text.startswith('{'):
                            return json.loads(text)
                        return text
                    except json.JSONDecodeError:
                        return item.get('text', '')
        return response
    
    # ========== DASHBOARD TOOLS ==========
    
    def search_dashboards(self, query=""):
        """Search for dashboards by query string"""
        return self.call_tool("search_dashboards", {"query": query})
    
    def get_dashboard_by_uid(self, uid):
        """Get full dashboard JSON by UID"""
        return self.call_tool("get_dashboard_by_uid", {"uid": uid})
    
    def get_dashboard_summary(self, uid):
        """Get compact dashboard overview"""
        return self.call_tool("get_dashboard_summary", {"uid": uid})
    
    def get_dashboard_property(self, uid, json_path):
        """Extract specific dashboard property using JSONPath"""
        return self.call_tool("get_dashboard_property", {
            "uid": uid,
            "jsonPath": json_path
        })
    
    def get_dashboard_panel_queries(self, uid):
        """Retrieve panel queries and information from a dashboard"""
        return self.call_tool("get_dashboard_panel_queries", {"uid": uid})
    
    def update_dashboard(self, dashboard=None, uid=None, folder_uid=None, message=None, 
                        operations=None, overwrite=False):
        """Create or update a dashboard"""
        args = {}
        if dashboard:
            args["dashboard"] = dashboard
        if uid:
            args["uid"] = uid
        if folder_uid:
            args["folderUid"] = folder_uid
        if message:
            args["message"] = message
        if operations:
            args["operations"] = operations
        if overwrite:
            args["overwrite"] = overwrite
        return self.call_tool("update_dashboard", args)
    
    # ========== FOLDER TOOLS ==========
    
    def search_folders(self, query=""):
        """Search for folders by query string"""
        return self.call_tool("search_folders", {"query": query})
    
    def create_folder(self, title, uid=None, parent_uid=None):
        """Create a new folder"""
        args = {"title": title}
        if uid:
            args["uid"] = uid
        if parent_uid:
            args["parentUid"] = parent_uid
        return self.call_tool("create_folder", args)
    
    # ========== DATASOURCE TOOLS ==========
    
    def list_datasources(self, ds_type=None):
        """List datasources, optionally filter by type"""
        args = {}
        if ds_type:
            args["type"] = ds_type
        return self.call_tool("list_datasources", args)
    
    def get_datasource_by_uid(self, uid):
        """Get datasource by UID"""
        return self.call_tool("get_datasource_by_uid", {"uid": uid})
    
    def get_datasource_by_name(self, name):
        """Get datasource by name"""
        return self.call_tool("get_datasource_by_name", {"name": name})
    
    # ========== PROMETHEUS TOOLS ==========
    
    def query_prometheus(self, datasource_uid, expr, start_time, end_time=None, 
                        query_type=None, step_seconds=None):
        """Query Prometheus using PromQL"""
        args = {
            "datasourceUid": datasource_uid,
            "expr": expr,
            "startTime": start_time
        }
        if end_time:
            args["endTime"] = end_time
        if query_type:
            args["queryType"] = query_type
        if step_seconds:
            args["stepSeconds"] = step_seconds
        return self.call_tool("query_prometheus", args)
    
    def list_prometheus_label_names(self, datasource_uid, start_rfc3339=None, 
                                    end_rfc3339=None, matches=None, limit=None):
        """List Prometheus label names"""
        args = {"datasourceUid": datasource_uid}
        if start_rfc3339:
            args["startRfc3339"] = start_rfc3339
        if end_rfc3339:
            args["endRfc3339"] = end_rfc3339
        if matches:
            args["matches"] = matches
        if limit:
            args["limit"] = limit
        return self.call_tool("list_prometheus_label_names", args)
    
    def list_prometheus_label_values(self, datasource_uid, label_name, start_rfc3339=None,
                                     end_rfc3339=None, matches=None, limit=None):
        """Get values for a specific Prometheus label"""
        args = {
            "datasourceUid": datasource_uid,
            "labelName": label_name
        }
        if start_rfc3339:
            args["startRfc3339"] = start_rfc3339
        if end_rfc3339:
            args["endRfc3339"] = end_rfc3339
        if matches:
            args["matches"] = matches
        if limit:
            args["limit"] = limit
        return self.call_tool("list_prometheus_label_values", args)
    
    def list_prometheus_metric_names(self, datasource_uid, limit=None, page=None, regex=None):
        """List Prometheus metric names"""
        args = {"datasourceUid": datasource_uid}
        if limit:
            args["limit"] = limit
        if page:
            args["page"] = page
        if regex:
            args["regex"] = regex
        return self.call_tool("list_prometheus_metric_names", args)
    
    def list_prometheus_metric_metadata(self, datasource_uid, metric=None, 
                                       limit=None, limit_per_metric=None):
        """List Prometheus metric metadata"""
        args = {"datasourceUid": datasource_uid}
        if metric:
            args["metric"] = metric
        if limit:
            args["limit"] = limit
        if limit_per_metric:
            args["limitPerMetric"] = limit_per_metric
        return self.call_tool("list_prometheus_metric_metadata", args)
    
    # ========== LOKI TOOLS ==========
    
    def query_loki_logs(self, datasource_uid, logql, start_rfc3339=None, end_rfc3339=None,
                       limit=None, direction=None):
        """Query Loki logs using LogQL"""
        args = {
            "datasourceUid": datasource_uid,
            "logql": logql
        }
        if start_rfc3339:
            args["startRfc3339"] = start_rfc3339
        if end_rfc3339:
            args["endRfc3339"] = end_rfc3339
        if limit:
            args["limit"] = limit
        if direction:
            args["direction"] = direction
        return self.call_tool("query_loki_logs", args)
    
    def query_loki_stats(self, datasource_uid, logql, start_rfc3339=None, end_rfc3339=None):
        """Get statistics about Loki log streams"""
        args = {
            "datasourceUid": datasource_uid,
            "logql": logql
        }
        if start_rfc3339:
            args["startRfc3339"] = start_rfc3339
        if end_rfc3339:
            args["endRfc3339"] = end_rfc3339
        return self.call_tool("query_loki_stats", args)
    
    def list_loki_label_names(self, datasource_uid, start_rfc3339=None, end_rfc3339=None):
        """List Loki label names"""
        args = {"datasourceUid": datasource_uid}
        if start_rfc3339:
            args["startRfc3339"] = start_rfc3339
        if end_rfc3339:
            args["endRfc3339"] = end_rfc3339
        return self.call_tool("list_loki_label_names", args)
    
    def list_loki_label_values(self, datasource_uid, label_name, 
                               start_rfc3339=None, end_rfc3339=None):
        """List values for a specific Loki label"""
        args = {
            "datasourceUid": datasource_uid,
            "labelName": label_name
        }
        if start_rfc3339:
            args["startRfc3339"] = start_rfc3339
        if end_rfc3339:
            args["endRfc3339"] = end_rfc3339
        return self.call_tool("list_loki_label_values", args)
    
    # ========== PYROSCOPE TOOLS ==========
    
    def fetch_pyroscope_profile(self, data_source_uid, profile_type, matchers=None,
                                start_rfc3339=None, end_rfc3339=None, max_node_depth=None):
        """Fetch a Pyroscope profile"""
        args = {
            "data_source_uid": data_source_uid,
            "profile_type": profile_type
        }
        if matchers:
            args["matchers"] = matchers
        if start_rfc3339:
            args["start_rfc_3339"] = start_rfc3339
        if end_rfc3339:
            args["end_rfc_3339"] = end_rfc3339
        if max_node_depth:
            args["max_node_depth"] = max_node_depth
        return self.call_tool("fetch_pyroscope_profile", args)
    
    def list_pyroscope_profile_types(self, data_source_uid, start_rfc3339=None, end_rfc3339=None):
        """List available Pyroscope profile types"""
        args = {"data_source_uid": data_source_uid}
        if start_rfc3339:
            args["start_rfc_3339"] = start_rfc3339
        if end_rfc3339:
            args["end_rfc_3339"] = end_rfc3339
        return self.call_tool("list_pyroscope_profile_types", args)
    
    def list_pyroscope_label_names(self, data_source_uid, matchers=None,
                                   start_rfc3339=None, end_rfc3339=None):
        """List Pyroscope label names"""
        args = {"data_source_uid": data_source_uid}
        if matchers:
            args["matchers"] = matchers
        if start_rfc3339:
            args["start_rfc_3339"] = start_rfc3339
        if end_rfc3339:
            args["end_rfc_3339"] = end_rfc3339
        return self.call_tool("list_pyroscope_label_names", args)
    
    def list_pyroscope_label_values(self, data_source_uid, name, matchers=None,
                                    start_rfc3339=None, end_rfc3339=None):
        """List Pyroscope label values"""
        args = {
            "data_source_uid": data_source_uid,
            "name": name
        }
        if matchers:
            args["matchers"] = matchers
        if start_rfc3339:
            args["start_rfc_3339"] = start_rfc3339
        if end_rfc3339:
            args["end_rfc_3339"] = end_rfc3339
        return self.call_tool("list_pyroscope_label_values", args)
    
    # ========== INCIDENT TOOLS ==========
    
    def list_incidents(self, status=None, drill=None, limit=None):
        """List incidents"""
        args = {}
        if status:
            args["status"] = status
        if drill is not None:
            args["drill"] = drill
        if limit:
            args["limit"] = limit
        return self.call_tool("list_incidents", args)
    
    def get_incident(self, incident_id):
        """Get incident by ID"""
        return self.call_tool("get_incident", {"id": incident_id})
    
    def create_incident(self, title=None, severity=None, room_prefix=None, status=None,
                       labels=None, is_drill=None, attach_url=None, attach_caption=None):
        """Create a new incident"""
        args = {}
        if title:
            args["title"] = title
        if severity:
            args["severity"] = severity
        if room_prefix:
            args["roomPrefix"] = room_prefix
        if status:
            args["status"] = status
        if labels:
            args["labels"] = labels
        if is_drill is not None:
            args["isDrill"] = is_drill
        if attach_url:
            args["attachUrl"] = attach_url
        if attach_caption:
            args["attachCaption"] = attach_caption
        return self.call_tool("create_incident", args)
    
    def add_activity_to_incident(self, incident_id, body, event_time=None):
        """Add a note to an incident"""
        args = {}
        if incident_id:
            args["incidentId"] = incident_id
        if body:
            args["body"] = body
        if event_time:
            args["eventTime"] = event_time
        return self.call_tool("add_activity_to_incident", args)
    
    # ========== ONCALL TOOLS ==========
    
    def list_oncall_schedules(self, schedule_id=None, team_id=None, page=None):
        """List OnCall schedules"""
        args = {}
        if schedule_id:
            args["scheduleId"] = schedule_id
        if team_id:
            args["teamId"] = team_id
        if page:
            args["page"] = page
        return self.call_tool("list_oncall_schedules", args)
    
    def get_current_oncall_users(self, schedule_id):
        """Get users currently on-call for a schedule"""
        return self.call_tool("get_current_oncall_users", {"scheduleId": schedule_id})
    
    def get_oncall_shift(self, shift_id):
        """Get OnCall shift details"""
        return self.call_tool("get_oncall_shift", {"shiftId": shift_id})
    
    def list_oncall_teams(self, page=None):
        """List OnCall teams"""
        args = {}
        if page:
            args["page"] = page
        return self.call_tool("list_oncall_teams", args)
    
    def list_oncall_users(self, user_id=None, username=None, page=None):
        """List OnCall users"""
        args = {}
        if user_id:
            args["userId"] = user_id
        if username:
            args["username"] = username
        if page:
            args["page"] = page
        return self.call_tool("list_oncall_users", args)
    
    def list_alert_groups(self, group_id=None, integration_id=None, route_id=None,
                         team_id=None, name=None, state=None, labels=None,
                         started_at=None, page=None):
        """List alert groups"""
        args = {}
        if group_id:
            args["id"] = group_id
        if integration_id:
            args["integrationId"] = integration_id
        if route_id:
            args["routeId"] = route_id
        if team_id:
            args["teamId"] = team_id
        if name:
            args["name"] = name
        if state:
            args["state"] = state
        if labels:
            args["labels"] = labels
        if started_at:
            args["startedAt"] = started_at
        if page:
            args["page"] = page
        return self.call_tool("list_alert_groups", args)
    
    def get_alert_group(self, alert_group_id):
        """Get specific alert group"""
        return self.call_tool("get_alert_group", {"alertGroupId": alert_group_id})
    
    # ========== ALERT RULE TOOLS ==========
    
    def list_alert_rules(self, label_selectors=None, limit=None, page=None):
        """List alert rules"""
        args = {}
        if label_selectors:
            args["label_selectors"] = label_selectors
        if limit:
            args["limit"] = limit
        if page:
            args["page"] = page
        return self.call_tool("list_alert_rules", args)
    
    def get_alert_rule_by_uid(self, uid):
        """Get alert rule by UID"""
        return self.call_tool("get_alert_rule_by_uid", {"uid": uid})
    
    def create_alert_rule(self, title, rule_group, folder_uid, condition, data,
                         exec_err_state, no_data_state, org_id, for_duration,
                         uid=None, annotations=None, labels=None):
        """Create alert rule"""
        args = {
            "title": title,
            "ruleGroup": rule_group,
            "folderUID": folder_uid,
            "condition": condition,
            "data": data,
            "execErrState": exec_err_state,
            "noDataState": no_data_state,
            "orgID": org_id,
            "for": for_duration
        }
        if uid:
            args["uid"] = uid
        if annotations:
            args["annotations"] = annotations
        if labels:
            args["labels"] = labels
        return self.call_tool("create_alert_rule", args)
    
    def update_alert_rule(self, uid, title, rule_group, folder_uid, condition, data,
                         exec_err_state, no_data_state, org_id, for_duration,
                         annotations=None, labels=None):
        """Update alert rule"""
        args = {
            "uid": uid,
            "title": title,
            "ruleGroup": rule_group,
            "folderUID": folder_uid,
            "condition": condition,
            "data": data,
            "execErrState": exec_err_state,
            "noDataState": no_data_state,
            "orgID": org_id,
            "for": for_duration
        }
        if annotations:
            args["annotations"] = annotations
        if labels:
            args["labels"] = labels
        return self.call_tool("update_alert_rule", args)
    
    def delete_alert_rule(self, uid):
        """Delete alert rule"""
        return self.call_tool("delete_alert_rule", {"uid": uid})
    
    def list_contact_points(self, name=None, limit=None):
        """List notification contact points"""
        args = {}
        if name:
            args["name"] = name
        if limit:
            args["limit"] = limit
        return self.call_tool("list_contact_points", args)
    
    # ========== SIFT TOOLS ==========
    
    def list_sift_investigations(self, limit=None):
        """List Sift investigations"""
        args = {}
        if limit:
            args["limit"] = limit
        return self.call_tool("list_sift_investigations", args)
    
    def get_sift_investigation(self, investigation_id):
        """Get Sift investigation by ID"""
        return self.call_tool("get_sift_investigation", {"id": investigation_id})
    
    def get_sift_analysis(self, investigation_id, analysis_id):
        """Get Sift analysis"""
        return self.call_tool("get_sift_analysis", {
            "investigationId": investigation_id,
            "analysisId": analysis_id
        })
    
    def find_error_pattern_logs(self, name, labels, start=None, end=None):
        """Search for elevated error patterns in logs"""
        args = {
            "name": name,
            "labels": labels
        }
        if start:
            args["start"] = start
        if end:
            args["end"] = end
        return self.call_tool("find_error_pattern_logs", args)
    
    def find_slow_requests(self, name, labels, start=None, end=None):
        """Search for slow requests in traces"""
        args = {
            "name": name,
            "labels": labels
        }
        if start:
            args["start"] = start
        if end:
            args["end"] = end
        return self.call_tool("find_slow_requests", args)
    
    def get_assertions(self, start_time, end_time, entity_type=None, entity_name=None,
                      env=None, site=None, namespace=None):
        """Get assertion summary for an entity"""
        args = {
            "startTime": start_time,
            "endTime": end_time
        }
        if entity_type:
            args["entityType"] = entity_type
        if entity_name:
            args["entityName"] = entity_name
        if env:
            args["env"] = env
        if site:
            args["site"] = site
        if namespace:
            args["namespace"] = namespace
        return self.call_tool("get_assertions", args)
    
    # ========== ANNOTATION TOOLS ==========
    
    def create_annotation(self, text=None, dashboard_id=None, dashboard_uid=None,
                         panel_id=None, tags=None, time=None, time_end=None, data=None):
        """Create annotation"""
        args = {}
        if text:
            args["text"] = text
        if dashboard_id:
            args["dashboardId"] = dashboard_id
        if dashboard_uid:
            args["dashboardUID"] = dashboard_uid
        if panel_id:
            args["panelId"] = panel_id
        if tags:
            args["tags"] = tags
        if time:
            args["time"] = time
        if time_end:
            args["timeEnd"] = time_end
        if data:
            args["data"] = data
        return self.call_tool("create_annotation", args)
    
    def create_graphite_annotation(self, what=None, when=None, tags=None, data=None):
        """Create Graphite-style annotation"""
        args = {}
        if what:
            args["what"] = what
        if when:
            args["when"] = when
        if tags:
            args["tags"] = tags
        if data:
            args["data"] = data
        return self.call_tool("create_graphite_annotation", args)
    
    def get_annotations(self, dashboard_uid=None, dashboard_id=None, panel_id=None,
                       from_time=None, to_time=None, tags=None, limit=None,
                       alert_id=None, alert_uid=None, user_id=None,
                       annotation_type=None, match_any=None):
        """Fetch annotations with filters"""
        args = {}
        if dashboard_uid:
            args["DashboardUID"] = dashboard_uid
        if dashboard_id:
            args["DashboardID"] = dashboard_id
        if panel_id:
            args["PanelID"] = panel_id
        if from_time:
            args["From"] = from_time
        if to_time:
            args["To"] = to_time
        if tags:
            args["Tags"] = tags
        if limit:
            args["Limit"] = limit
        if alert_id:
            args["AlertID"] = alert_id
        if alert_uid:
            args["AlertUID"] = alert_uid
        if user_id:
            args["UserID"] = user_id
        if annotation_type:
            args["Type"] = annotation_type
        if match_any is not None:
            args["MatchAny"] = match_any
        return self.call_tool("get_annotations", args)
    
    def get_annotation_tags(self, tag=None, limit=None):
        """Get annotation tags"""
        args = {}
        if tag:
            args["tag"] = tag
        if limit:
            args["limit"] = limit
        return self.call_tool("get_annotation_tags", args)
    
    def update_annotation(self, annotation_id, text=None, tags=None, time=None,
                         time_end=None, data=None):
        """Update annotation (full update)"""
        args = {}
        if annotation_id:
            args["id"] = annotation_id
        if text:
            args["text"] = text
        if tags:
            args["tags"] = tags
        if time:
            args["time"] = time
        if time_end:
            args["timeEnd"] = time_end
        if data:
            args["data"] = data
        return self.call_tool("update_annotation", args)
    
    def patch_annotation(self, annotation_id, text=None, tags=None, time=None,
                        time_end=None, data=None):
        """Patch annotation (partial update)"""
        args = {}
        if annotation_id:
            args["id"] = annotation_id
        if text:
            args["text"] = text
        if tags:
            args["tags"] = tags
        if time:
            args["time"] = time
        if time_end:
            args["timeEnd"] = time_end
        if data:
            args["data"] = data
        return self.call_tool("patch_annotation", args)
    
    # ========== NAVIGATION TOOLS ==========
    
    def generate_deeplink(self, resource_type, dashboard_uid=None, panel_id=None,
                         datasource_uid=None, time_range=None, query_params=None):
        """Generate deeplink URL"""
        args = {"resourceType": resource_type}
        if dashboard_uid:
            args["dashboardUid"] = dashboard_uid
        if panel_id:
            args["panelId"] = panel_id
        if datasource_uid:
            args["datasourceUid"] = datasource_uid
        if time_range:
            args["timeRange"] = time_range
        if query_params:
            args["queryParams"] = query_params
        return self.call_tool("generate_deeplink", args)
    
    # ========== ADMIN TOOLS ==========
    
    def list_teams(self, query=None):
        """Search for teams"""
        args = {}
        if query:
            args["query"] = query
        return self.call_tool("list_teams", args)
    
    def list_users_by_org(self):
        """List users by organization"""
        return self.call_tool("list_users_by_org", {})
    
    # ========== UTILITY METHODS ==========
    
    def list_tools(self):
        """List all available tools"""
        return self.send_request("tools/list")
    
    def close(self):
        """Stop listening to SSE"""
        self.stop_listening = True
        print("\n✓ Connection closed")


# ========== DEMO SCRIPT ==========

if __name__ == "__main__":
    client = GrafanaMCPClient("http://localhost:8000")
    
    try:
        client.connect()
        
        # List datasources
        print("="*70)
        print("DATASOURCES")
        print("="*70)
        result = client.list_datasources()
        datasources = client.extract_result_text(result)
        
        if isinstance(datasources, list):
            for ds in datasources:
                print(f"  • {ds.get('name')} ({ds.get('type')}) - UID: {ds.get('uid')}")
        print()
        
        # Search dashboards
        print("="*70)
        print("ALL DASHBOARDS")
        print("="*70)
        result = client.search_dashboards("")
        dashboards = client.extract_result_text(result)
        
        if isinstance(dashboards, list):
            if len(dashboards) == 0:
                print("  No dashboards found")
            else:
                for db in dashboards:
                    print(f"  • {db.get('title')} - UID: {db.get('uid')}")
        print()
        
        # Query Prometheus
        print("="*70)
        print("PROMETHEUS QUERY")
        print("="*70)
        try:
            # Find Prometheus datasource
            prom_ds = next((ds for ds in datasources if ds.get('type') == 'prometheus'), None)
            if prom_ds:
                print(f"Using datasource: {prom_ds['name']}")
                result = client.query_prometheus(
                    datasource_uid=prom_ds['uid'],
                    expr="up",
                    start_time="now-5m"
                )
                metrics = client.extract_result_text(result)
                print(json.dumps(metrics, indent=2)[:500] + "...")
            else:
                print("  No Prometheus datasource found")
        except Exception as e:
            print(f"  Error: {e}")
        print()
        
        # Search folders
        print("="*70)
        print("FOLDERS")
        print("="*70)
        result = client.search_folders("")
        folders = client.extract_result_text(result)
        
        if isinstance(folders, list):
            if len(folders) == 0:
                print("  No folders found")
            else:
                for folder in folders:
                    print(f"  • {folder.get('title')} - UID: {folder.get('uid')}")
        
    except KeyboardInterrupt:
        print("\n\nStopped by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()
