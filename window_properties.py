import json
import time
import requests
from websocket import create_connection
from pathlib import Path

# Native browser API prefixes - used to identify native vs application objects
NATIVE_PREFIXES = [
    "HTML", "SVG", "MathML", "RTC", "IDB", "Media", "Audio", "Video",
    "WebGL", "Canvas", "Crypto", "File", "Blob", "Form", "Input",
    "Mutation", "Intersection", "Resize", "Performance", "Navigation",
    "Storage", "Location", "History", "Navigator", "Screen", "Window",
    "Document", "Element", "Node", "Event", "Promise", "Array",
    "String", "Number", "Boolean", "Date", "RegExp", "Error", "Function",
    "Map", "Set", "WeakMap", "WeakSet", "Proxy", "Reflect", "Symbol",
    "Intl", "JSON", "Math", "Console", "TextEncoder", "TextDecoder",
    "ReadableStream", "WritableStream", "TransformStream", "AbortController",
    "URL", "URLSearchParams", "Headers", "Request", "Response", "Fetch",
    "Worker", "SharedWorker", "ServiceWorker", "BroadcastChannel",
    "MessageChannel", "MessagePort", "ImageData", "ImageBitmap",
    "OffscreenCanvas", "Path2D", "CanvasGradient", "CanvasPattern",
    "Geolocation", "Notification", "PushManager", "Cache", "IndexedDB"
]

def get_ws_url():
    resp = requests.get("http://localhost:9222/json")
    return resp.json()[0]["webSocketDebuggerUrl"]


class CDPClient:
    def __init__(self, ws_url):
        self.ws = create_connection(ws_url)
        self.msg_id = 1
        self.navigation_detected = False
        
        # Enable Page events
        self.send("Page.enable")
        
    def send(self, method, params=None):
        current_id = self.msg_id
        self.msg_id += 1
        
        payload = {"id": current_id, "method": method}
        if params:
            payload["params"] = params
        self.ws.send(json.dumps(payload))
        
        while True:
            resp = json.loads(self.ws.recv())
            
            # If it's the response we're waiting for
            if resp.get("id") == current_id:
                return resp
            
            # If it's an event
            if "method" in resp:
                self._handle_event(resp)
                
    def _handle_event(self, msg):
        method = msg.get("method")
        # Detect navigation/reload events
        if method in ["Page.loadEventFired", "Page.frameNavigated", "Runtime.executionContextsCleared"]:
            print(f"\n!!! Navigation detected: {method} !!!")
            self.navigation_detected = True
            
    def wait_for_navigation_or_timeout(self, timeout):
        """Wait for navigation event or timeout. Returns True if navigation occurred."""
        # If navigation already detected during previous commands
        if self.navigation_detected:
            self.navigation_detected = False
            return True
            
        start_time = time.time()
        self.ws.settimeout(0.1) # Short timeout for non-blocking check
        
        while time.time() - start_time < timeout:
            try:
                resp = json.loads(self.ws.recv())
                if "method" in resp:
                    self._handle_event(resp)
                    if self.navigation_detected:
                        self.navigation_detected = False
                        self.ws.settimeout(None) # Reset timeout
                        return True
            except Exception:
                # Timeout, continue loop
                pass
                
        self.ws.settimeout(None) # Reset timeout
        return False
        
    def close(self):
        self.ws.close()

def cdp_send(ws, method, params=None, msg_id=1):
    # Legacy wrapper for compatibility if needed, but we should switch to client
    pass 

def is_application_object(className, name):
    """
    Heuristically determine if an object is an application object (not a native browser API).
    Returns True if it's likely an application object, False if it's likely native.
    """
    if not name:
        return False
    
    # First, check if className matches native patterns - if so, it's definitely native
    if className:
        for prefix in NATIVE_PREFIXES:
            if className.startswith(prefix):
                return False
    
    # If name looks like a native API, it's native
    if name.startswith(("HTML", "SVG", "RTC", "IDB", "WebGL", "Media", "Audio", "Video")):
        return False
    
    # Skip common native browser globals
    native_globals = [
        "window", "self", "top", "parent", "frames", "document", "navigator",
        "location", "history", "screen", "console", "localStorage", "sessionStorage",
        "indexedDB", "caches", "performance", "fetch", "XMLHttpRequest", "WebSocket",
        "Blob", "File", "FileReader", "FormData", "URL", "URLSearchParams",
        "Headers", "Request", "Response", "AbortController", "Event", "CustomEvent",
        "Promise", "Map", "Set", "WeakMap", "WeakSet", "Proxy", "Reflect",
        "Symbol", "Intl", "JSON", "Math", "Date", "RegExp", "Error", "Array",
        "String", "Number", "Boolean", "Object", "Function", "ArrayBuffer",
        "DataView", "Int8Array", "Uint8Array", "Int16Array", "Uint16Array",
        "Int32Array", "Uint32Array", "Float32Array", "Float64Array"
    ]
    if name in native_globals:
        return False
    # If className is "Object" or empty, and it passed the blacklist checks above, it is likely an application object
    # This allows objects like "ZD", "__REDUX_STATE__", "x-zdata" to be captured
    if className == "Object" or not className:
        return True
    
    # If we get here and className doesn't match native patterns, it might be application
    # But be conservative - only if it's clearly not native
    return True

def fully_resolve_object_flat(client, object_id, base_path, flat_dict, visited=None, depth=0, max_depth=20):
    """
    Recursively resolve an object and add all properties to a flat dictionary with dot paths.
    """
    if visited is None:
        visited = set()
    
    if depth > max_depth or object_id in visited:
        return
    
    visited.add(object_id)
    
    try:
        props = client.send("Runtime.getProperties", {
            "objectId": object_id,
            "ownProperties": True
        })
        
        for prop in props.get("result", {}).get("result", []):
            name = prop["name"]
            value = prop.get("value", {})
            value_type = value.get("type", "unknown")
            className = value.get("className", "")
            
            # Skip native APIs at deeper levels, but be more permissive - only skip if we're certain it's native
            # Check if it's an application object first - if so, never skip it
            is_app_obj = is_application_object(className, name)
            if depth > 0 and not is_app_obj:
                continue
            
            prop_path = f"{base_path}.{name}" if base_path else name
            
            # Only store actual values, no metadata
            if value_type == "string":
                flat_dict[prop_path] = value.get("value")
            elif value_type in ["number", "boolean"]:
                flat_dict[prop_path] = value.get("value")
            elif value_type == "object":
                if value.get("subtype") == "null":
                    flat_dict[prop_path] = None
                elif value.get("objectId"):
                    nested_obj_id = value.get("objectId")
                    
                    # Recursively resolve if it's an application object
                    # This ensures we capture all application objects even if they have native-like classNames
                    if is_app_obj:
                        fully_resolve_object_flat(client, nested_obj_id, prop_path, flat_dict, visited.copy(), depth + 1, max_depth)
                    # Don't add anything for skipped native APIs
                else:
                    flat_dict[prop_path] = value.get("value")
            elif value_type == "function":
                # Skip functions - don't add anything
                pass
            else:
                flat_dict[prop_path] = value.get("value")
    
    except Exception as e:
        # Skip errors - don't add error metadata
        pass

def collect_window_properties(client):
    """Collect all window properties into a flat dictionary."""
    # Get current URL using CDP
    current_url = None
    try:
        # Try Runtime.evaluate first
        url_resp = client.send("Runtime.evaluate", {
            "expression": "window.location.href",
            "returnByValue": True
        })
        if "error" not in url_resp:
            current_url = url_resp.get("result", {}).get("value")
        
        # Fallback: Try Page.getFrameTree if Runtime.evaluate fails
        if not current_url:
            frame_resp = client.send("Page.getFrameTree", {})
            if "error" not in frame_resp:
                frame_tree = frame_resp.get("result", {}).get("frameTree", {})
                current_url = frame_tree.get("frame", {}).get("url")
    except Exception as e:
        print(f"Warning: Could not get URL: {e}")
    
    if not current_url:
        # Last resort: try document.location.href
        try:
            url_resp = client.send("Runtime.evaluate", {
                "expression": "document.location.href",
                "returnByValue": True
            })
            if "error" not in url_resp:
                current_url = url_resp.get("result", {}).get("value")
        except:
            pass
    
    if not current_url:
        raise RuntimeError("Failed to retrieve page URL via CDP")
    
    # Step 1: Get window object
    resp = client.send("Runtime.evaluate", {
        "expression": "window",
        "returnByValue": False
    })

    if "error" in resp or not resp["result"]["result"].get("objectId"):
        print("Window object not found!")
        return None, current_url

    window_obj = resp["result"]["result"]["objectId"]
    
    # Get all properties of window
    print("\n=== Getting window properties ===")
    props = client.send("Runtime.getProperties", {
        "objectId": window_obj,
        "ownProperties": True
    })

    # This will be our flat dictionary with dot-separated paths
    flat_dict = {}
    
    # Collect all properties to process (only from window)
    all_props = list(props["result"]["result"])
    
    print(f"\n=== Processing {len(all_props)} total properties ===")
    
    skipped_count = 0
    processed_count = 0
    
    for prop in all_props:
        name = prop["name"]
        value = prop.get("value", {})
        value_type = value.get("type", "unknown")
        className = value.get("className", "")
        
        # Use heuristic to determine if this is an application object
        is_app_object = is_application_object(className, name)
        
        # Skip native browser APIs and circular references
        if not is_app_object:
            skipped_count += 1
            continue
        
        # Only store actual values, no metadata
        if value_type == "string":
            flat_dict[name] = value.get("value")
        elif value_type in ["number", "boolean"]:
            flat_dict[name] = value.get("value")
        elif value_type == "object" and value.get("objectId"):
            obj_id = value.get("objectId")
            
            print(f"  {name}: object ({className}) - resolving...")
            
            # Fully resolve the object into flat dict (only for non-native objects)
            # Use higher max_depth to ensure we capture deeply nested application objects
            fully_resolve_object_flat(client, obj_id, name, flat_dict, max_depth=10)
            
            print(f"    -> Resolved {name}")
        elif value_type == "function":
            # Skip functions - don't add anything
            pass
        else:
            flat_dict[name] = value.get("value")
        
        processed_count += 1
    
    print(f"Processed: {processed_count}, Skipped: {skipped_count}")
    return flat_dict, current_url

def main():
    ws_url = get_ws_url()
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "window_properties_flat.json"
    
    print("Connecting to:", ws_url)
    client = CDPClient(ws_url)
    time.sleep(0.2)
    
    # Load existing history if available
    history_db = {}
    if output_file.exists():
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)
                
            # Get current URL for migration
            migration_url = None
            try:
                url_resp = client.send("Runtime.evaluate", {
                    "expression": "window.location.href",
                    "returnByValue": True
                })
                if "error" not in url_resp:
                    migration_url = url_resp.get("result", {}).get("value")
                if not migration_url:
                    frame_resp = client.send("Page.getFrameTree", {})
                    if "error" not in frame_resp:
                        migration_url = frame_resp.get("result", {}).get("frameTree", {}).get("frame", {}).get("url")
            except Exception as e:
                print(f"Warning: Could not get URL for migration: {e}")
            
            # Migrate old format to new format if necessary
            migration_ts = time.time()
            for k, v in loaded_data.items():
                if not isinstance(v, list):
                    # Old format: key -> value. Convert to key -> [{ts, value, url}]
                    history_db[k] = [{"timestamp": migration_ts, "value": v, "url": migration_url or ""}]
                else:
                    # Assume new format, but ensure url key exists
                    history_db[k] = v
                    for entry in history_db[k]:
                        if "url" not in entry:
                            entry["url"] = migration_url or ""
                    
            print(f"Loaded existing history with {len(history_db)} keys")
        except Exception as e:
            print(f"Error loading existing file: {e}")
    
    print("Starting continuous collection (every 10s or on navigation)...")
    
    try:
        while True:
            start_time = time.time()
            current_ts = start_time
            
            print(f"\n--- Collection cycle at {current_ts} ---")
            
            current_snapshot, current_url = collect_window_properties(client)
            
            if current_snapshot is not None:
                changes_count = 0
                
                # Update history with new/changed values
                for key, value in current_snapshot.items():
                    if key not in history_db:
                        # New key
                        history_db[key] = [{"timestamp": current_ts, "value": value, "url": current_url}]
                        changes_count += 1
                    else:
                        # Existing key, check if value changed
                        last_entry = history_db[key][-1]
                        if last_entry["value"] != value:
                            history_db[key].append({"timestamp": current_ts, "value": value, "url": current_url})
                            changes_count += 1
                
                # Check for deleted keys
                for key in list(history_db.keys()):
                    if key not in current_snapshot:
                        last_entry = history_db[key][-1]
                        # If it wasn't already marked as deleted (None)
                        if last_entry["value"] is not None:
                            history_db[key].append({"timestamp": current_ts, "value": None, "url": current_url})
                            changes_count += 1
                
                print(f"Saving {changes_count} changes to {output_file}")
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(history_db, f, indent=2, ensure_ascii=False)
            
            # Wait for next cycle or navigation event
            print("Waiting for next cycle (10s) or navigation...")
            if client.wait_for_navigation_or_timeout(10):
                print("\n>>> Navigation event detected! Triggering immediate collection...")
                # Loop will restart immediately
            else:
                print("\n>>> Timeout reached. Starting next cycle...")
            
    except KeyboardInterrupt:
        print("\nStopping collection...")
    finally:
        client.close()


if __name__ == "__main__":
    main()