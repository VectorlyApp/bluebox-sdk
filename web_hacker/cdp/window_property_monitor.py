#!/usr/bin/env python3
"""
Window property monitoring functionality for CDP web scraping.
Tracks window properties over time, collecting on a schedule and on navigation events.
"""

import json
import logging
import os
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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


class WindowPropertyMonitor:
    """Monitors window properties using CDP, tracking changes over time."""
    
    def __init__(self, output_dir, paths):
        self.output_dir = output_dir
        self.paths = paths
        
        # Window properties history
        self.history_db = {}
        
        # Collection state
        self.collection_interval = 10.0  # seconds
        self.last_collection_time = 0
        self.navigation_detected = False
        self.page_ready = False  # Track if page is ready for collection
        
        # Output path
        root_output_dir = paths.get('output_dir', output_dir)
        self.window_properties_dir = os.path.join(root_output_dir, "window_properties")
        os.makedirs(self.window_properties_dir, exist_ok=True)
        self.output_file = os.path.join(self.window_properties_dir, "window_properties_flat.json")
        
        # Load existing history
        self._load_history()
    
    def _load_history(self):
        """Load existing window properties history from file."""
        if os.path.exists(self.output_file):
            try:
                with open(self.output_file, "r", encoding="utf-8") as f:
                    loaded_data = json.load(f)
                
                # Migrate old format to new format if necessary
                migration_ts = time.time()
                migration_url = None  # Will be set during first collection
                
                for k, v in loaded_data.items():
                    if not isinstance(v, list):
                        # Old format: key -> value. Convert to key -> [{ts, value, url}]
                        self.history_db[k] = [{"timestamp": migration_ts, "value": v, "url": ""}]
                    else:
                        # Assume new format, but ensure url key exists
                        self.history_db[k] = v
                        for entry in self.history_db[k]:
                            if "url" not in entry:
                                entry["url"] = ""
                
                logger.info(f"Loaded existing history with {len(self.history_db)} keys")
            except Exception as e:
                logger.warning(f"Error loading existing file: {e}")
    
    def _save_history(self):
        """Save window properties history to file."""
        try:
            with open(self.output_file, "w", encoding="utf-8") as f:
                json.dump(self.history_db, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving window properties: {e}")
    
    def setup_window_property_monitoring(self, cdp_session):
        """Setup window property monitoring via CDP session."""
        # Enable Page domain for navigation events
        cdp_session.send("Page.enable")
        
        # Enable Runtime domain for property access
        cdp_session.send("Runtime.enable")
        
        # Check if page is already loaded
        try:
            result = cdp_session.send_and_wait("Runtime.evaluate", {
                "expression": "document.readyState",
                "returnByValue": True
            }, timeout=2)
            if result and result.get("result", {}).get("value") == "complete":
                self.page_ready = True
                logger.info("Page already loaded, marking as ready")
        except Exception:
            pass
            
        logger.info("Window property monitoring enabled")
    
    def handle_window_property_message(self, msg, cdp_session):
        """Handle window property-related CDP messages."""
        method = msg.get("method")
        
        # Detect navigation events
        if method == "Runtime.executionContextsCleared":
            # JS context cleared - page is navigating, but NOT ready yet
            logger.debug("JavaScript context cleared - navigation starting")
            self.page_ready = False  # Page is NOT ready yet
            self.navigation_detected = True
            return True
        
        elif method == "Page.frameNavigated":
            # Frame navigated - page might be loading
            logger.debug("Frame navigated")
            self.navigation_detected = True
            # Don't mark as ready yet - wait for loadEventFired
            return True
        
        elif method == "Page.loadEventFired":
            # Page is fully loaded - NOW we can collect
            logger.info("Page load event fired - page is ready")
            self.page_ready = True
            self.navigation_detected = True
            # Wait a bit for page to fully initialize JavaScript
            time.sleep(0.5)
            # Trigger immediate collection
            self._collect_window_properties(cdp_session)
            return True
        
        return False
    
    def _is_application_object(self, className, name):
        """Heuristically determine if an object is an application object."""
        if not name:
            return False
        
        # First, check if className matches native patterns
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
        if className == "Object" or not className:
            return True
        
        return True
    
    def _fully_resolve_object_flat(self, cdp_session, object_id, base_path, flat_dict, visited=None, depth=0, max_depth=10):
        """Recursively resolve an object and add all properties to a flat dictionary with dot paths."""
        if visited is None:
            visited = set()
        
        if depth > max_depth or object_id in visited:
            return
        
        visited.add(object_id)
        
        try:
            props_result = cdp_session.send_and_wait("Runtime.getProperties", {
                "objectId": object_id,
                "ownProperties": True
            }, timeout=5)
            
            props_list = props_result.get("result", [])
            
            for prop in props_list:
                name = prop["name"]
                value = prop.get("value", {})
                value_type = value.get("type", "unknown")
                className = value.get("className", "")
                
                # Skip native APIs at deeper levels
                is_app_obj = self._is_application_object(className, name)
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
                        if is_app_obj:
                            self._fully_resolve_object_flat(cdp_session, nested_obj_id, prop_path, flat_dict, visited.copy(), depth + 1, max_depth)
                elif value_type == "function":
                    pass  # Skip functions
                else:
                    flat_dict[prop_path] = value.get("value")
        
        except Exception as e:
            logger.debug(f"Error resolving object {base_path}: {e}")
    
    def _get_current_url(self, cdp_session):
        """Get current page URL using CDP. Tries Page.getFrameTree first (doesn't require JS)."""
        try:
            # Try Page.getFrameTree first - this works even if JavaScript isn't ready
            frame_tree = cdp_session.send_and_wait("Page.getFrameTree", {}, timeout=5)
            if frame_tree and "frameTree" in frame_tree:
                current_url = frame_tree.get("frameTree", {}).get("frame", {}).get("url")
                if current_url:
                    return current_url
            
            # Fallback: Try Runtime.evaluate (requires JS to be ready)
            try:
                result = cdp_session.send_and_wait("Runtime.evaluate", {
                    "expression": "window.location.href",
                    "returnByValue": True
                }, timeout=3)
                if result and "result" in result:
                    current_url = result["result"].get("value")
                    if current_url:
                        return current_url
            except Exception:
                # Runtime.evaluate failed, try document.location.href as last resort
                try:
                    result = cdp_session.send_and_wait("Runtime.evaluate", {
                        "expression": "document.location.href",
                        "returnByValue": True
                    }, timeout=3)
                    if result and "result" in result:
                        current_url = result["result"].get("value")
                        if current_url:
                            return current_url
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Could not get URL: {e}")
        
        # Return placeholder if we can't get URL - don't fail collection
        return "unknown"
    
    def _collect_window_properties(self, cdp_session):
        """Collect all window properties into a flat dictionary."""
        try:
            # Check if Runtime context is ready (quick check with short timeout)
            try:
                # Try a simple evaluation to check if JS context is ready
                test_result = cdp_session.send_and_wait("Runtime.evaluate", {
                    "expression": "1+1",
                    "returnByValue": True
                }, timeout=2)
                # Check if result has error or if result structure is invalid
                if not test_result:
                    logger.debug("Runtime context not ready yet, skipping collection")
                    return
                if isinstance(test_result, dict):
                    if "error" in test_result:
                        logger.debug("Runtime context has error, skipping collection")
                        return
                    if "result" not in test_result:
                        logger.debug("Runtime context returned invalid response, skipping collection")
                        return
            except TimeoutError:
                logger.debug("Runtime context check timed out, skipping collection")
                return
            except Exception as e:
                logger.debug(f"Runtime context check failed: {e}, skipping collection")
                return
            
            current_url = self._get_current_url(cdp_session)
            # Don't fail if URL is unknown - continue with collection
            
            # Get window object
            result = cdp_session.send_and_wait("Runtime.evaluate", {
                "expression": "window",
                "returnByValue": False
            }, timeout=5)
            
            if not result or not result.get("result", {}).get("objectId"):
                logger.debug("Window object not found, skipping collection")
                return
            
            window_obj = result["result"]["objectId"]
            
            # Get all properties of window
            props_result = cdp_session.send_and_wait("Runtime.getProperties", {
                "objectId": window_obj,
                "ownProperties": True
            }, timeout=10)
            
            flat_dict = {}
            all_props = props_result.get("result", [])
            
            skipped_count = 0
            processed_count = 0
            
            for prop in all_props:
                name = prop["name"]
                value = prop.get("value", {})
                value_type = value.get("type", "unknown")
                className = value.get("className", "")
                
                is_app_object = self._is_application_object(className, name)
                
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
                    self._fully_resolve_object_flat(cdp_session, obj_id, name, flat_dict, max_depth=10)
                elif value_type == "function":
                    pass  # Skip functions
                else:
                    flat_dict[name] = value.get("value")
                
                processed_count += 1
            
            # Update history
            current_ts = time.time()
            changes_count = 0
            
            # Update history with new/changed values
            for key, value in flat_dict.items():
                if key not in self.history_db:
                    # New key
                    self.history_db[key] = [{"timestamp": current_ts, "value": value, "url": current_url}]
                    changes_count += 1
                else:
                    # Existing key, check if value changed
                    last_entry = self.history_db[key][-1]
                    if last_entry["value"] != value:
                        self.history_db[key].append({"timestamp": current_ts, "value": value, "url": current_url})
                        changes_count += 1
            
            # Check for deleted keys
            for key in list(self.history_db.keys()):
                if key not in flat_dict:
                    last_entry = self.history_db[key][-1]
                    if last_entry["value"] is not None:
                        self.history_db[key].append({"timestamp": current_ts, "value": None, "url": current_url})
                        changes_count += 1
            
            if changes_count > 0:
                self._save_history()
                logger.info(f"Window properties: {processed_count} processed, {skipped_count} skipped, {changes_count} changes saved")
            
        except Exception as e:
            logger.error(f"Error collecting window properties: {e}")
    
    def check_and_collect(self, cdp_session):
        """Check if it's time to collect and collect if needed."""
        # Don't collect until page is ready (after first navigation)
        if not self.page_ready:
            return
        
        current_time = time.time()
        
        # Collect on navigation or if interval has passed
        should_collect = (
            self.navigation_detected or
            (current_time - self.last_collection_time) >= self.collection_interval
        )
        
        if should_collect:
            self.navigation_detected = False
            self.last_collection_time = current_time
            self._collect_window_properties(cdp_session)

    def force_collect(self, cdp_session):
        """Force immediate collection of window properties."""
        self._collect_window_properties(cdp_session)
    
    def get_window_property_summary(self):
        """Get summary of window property monitoring."""
        total_keys = len(self.history_db)
        total_entries = sum(len(history) for history in self.history_db.values())
        
        return {
            "total_keys": total_keys,
            "total_history_entries": total_entries,
            "output_file": self.output_file
        }

