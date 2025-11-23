import json
import time
import requests
import os
from websocket import create_connection
from pathlib import Path

def get_ws_url():
    resp = requests.get("http://localhost:9222/json")
    return resp.json()[0]["webSocketDebuggerUrl"]

def cdp_send(ws, method, params=None, msg_id=1):
    payload = {"id": msg_id, "method": method}
    if params:
        payload["params"] = params
    ws.send(json.dumps(payload))
    return json.loads(ws.recv())

def sanitize_filename(name):
    """Convert a property name to a safe filename."""
    # Replace invalid filename characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    # Limit length
    if len(name) > 200:
        name = name[:200]
    return name

def is_application_object(className, name):
    """
    Heuristically determine if an object is an application object (not a native browser API).
    Returns True if it's likely an application object, False if it's likely native.
    """
    if not name:
        return False
    
    # Application objects often have these patterns in their names
    application_patterns = [
        "__",  # Internal state objects like __APOLLO_STATE__, __REDUX_STATE__
        "State", "STATE",  # State management
        "Config", "config", "options", "Options",  # Configuration objects
        "Data", "data",  # Data objects
        "Store", "store",  # Store objects
        "App", "app",  # Application objects
    ]
    
    # Check if name matches application patterns
    for pattern in application_patterns:
        if pattern in name:
            return True
    
    # Objects with className "Object" are often application objects (not native APIs)
    # Native APIs usually have specific class names like "HTMLDivElement", "Window", etc.
    if className == "Object" or not className:
        # But exclude if it looks like a native API by name
        if name.startswith(("HTML", "SVG", "RTC", "IDB", "WebGL")):
            return False
        return True
    
    # If className doesn't match native patterns, it's likely application code
    native_prefixes = [
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
    
    # If className matches native patterns, it's not an application object
    for prefix in native_prefixes:
        if className.startswith(prefix):
            return False
    
    # If we get here, it's likely an application object (custom class name)
    return True

def is_native_api(className, name):
    """Check if this is a native browser API that we should skip."""
    if not className:
        return False
    
    # If it's an application object, don't skip it
    if is_application_object(className, name):
        return False
    
    # Skip native browser constructors and APIs
    native_prefixes = [
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
    
    for prefix in native_prefixes:
        if className.startswith(prefix):
            return True
    
    # Skip if name looks like a native API
    if name and (name.startswith("HTML") or name.startswith("SVG") or 
                 name.startswith("RTC") or name in ["window", "self", "top", "parent", "frames"]):
        return True
    
    return False

def fully_resolve_object(ws, object_id, visited=None, depth=0, max_depth=5):
    """
    Recursively resolve an object and all its properties.
    Returns a dictionary with all resolved values.
    """
    if visited is None:
        visited = set()
    
    if depth > max_depth or object_id in visited:
        return {"_error": "Max depth reached or circular reference", "objectId": object_id}
    
    visited.add(object_id)
    
    try:
        props = cdp_send(ws, "Runtime.getProperties", {
            "objectId": object_id,
            "ownProperties": True
        })
        
        resolved = {}
        
        for prop in props.get("result", {}).get("result", []):
            name = prop["name"]
            value = prop.get("value", {})
            value_type = value.get("type", "unknown")
            className = value.get("className", "")
            
            # Skip native APIs at deeper levels
            if depth > 0 and is_native_api(className, name):
                continue
            
            prop_data = {
                "type": value_type,
                "writable": prop.get("writable", False),
                "configurable": prop.get("configurable", False),
                "enumerable": prop.get("enumerable", False)
            }
            
            if value_type == "string":
                prop_data["value"] = value.get("value")
            elif value_type in ["number", "boolean"]:
                prop_data["value"] = value.get("value")
            elif value_type == "object":
                if value.get("subtype") == "null":
                    prop_data["value"] = None
                elif value.get("objectId"):
                    nested_obj_id = value.get("objectId")
                    prop_data["className"] = className
                    prop_data["description"] = value.get("description", "")
                    prop_data["objectId"] = nested_obj_id
                    
                    # Only recursively resolve if not a native API
                    if not is_native_api(className, name):
                        prop_data["nested"] = fully_resolve_object(ws, nested_obj_id, visited.copy(), depth + 1, max_depth)
                    else:
                        prop_data["nested"] = {"_skipped": "Native API"}
                else:
                    prop_data["value"] = value.get("value")
            elif value_type == "function":
                prop_data["description"] = value.get("description", "")
            else:
                prop_data["value"] = value.get("value")
            
            resolved[name] = prop_data
        
        # Also get internal properties (like [[Prototype]])
        internal_props = props.get("result", {}).get("internalProperties", [])
        if internal_props:
            resolved["_internalProperties"] = []
            for internal in internal_props:
                internal_data = {"name": internal.get("name")}
                internal_value = internal.get("value", {})
                if internal_value.get("objectId"):
                    internal_data["objectId"] = internal_value.get("objectId")
                    internal_data["className"] = internal_value.get("className", "Object")
                resolved["_internalProperties"].append(internal_data)
        
        return resolved
    
    except Exception as e:
        return {"_error": str(e), "objectId": object_id}

def get_global_variables(ws, msg_id):
    """Get all global variables using JavaScript evaluation."""
    print("\n=== Getting global variables via JavaScript ===")
    
    # Get all global variables by evaluating a script that collects them
    # This script tries multiple methods to capture all global variables
    script = """
    (function() {
        const globals = {};
        const seen = new Set();
        
        // Method 1: Get all enumerable properties from window
        try {
            for (let key in window) {
                if (!seen.has(key)) {
                    try {
                        globals[key] = window[key];
                        seen.add(key);
                    } catch(e) {}
                }
            }
        } catch(e) {}
        
        // Method 2: Get all own properties from window (including non-enumerable)
        try {
            Object.getOwnPropertyNames(window).forEach(key => {
                if (!seen.has(key) && key !== 'window' && key !== 'self') {
                    try {
                        globals[key] = window[key];
                        seen.add(key);
                    } catch(e) {}
                }
            });
        } catch(e) {}
        
        // Method 3: Get properties from globalThis (ES2020)
        try {
            if (typeof globalThis !== 'undefined') {
                for (let key in globalThis) {
                    if (!seen.has(key) && key !== 'window' && key !== 'self' && key !== 'globalThis') {
                        try {
                            globals[key] = globalThis[key];
                            seen.add(key);
                        } catch(e) {}
                    }
                }
            }
        } catch(e) {}
        
        // Method 4: Try to get variables from the global scope
        try {
            // Use eval in a way that captures variables
            const keys = Object.keys(this);
            keys.forEach(key => {
                if (!seen.has(key) && key !== 'window' && key !== 'self' && key !== 'this') {
                    try {
                        globals[key] = this[key];
                        seen.add(key);
                    } catch(e) {}
                }
            });
        } catch(e) {}
        
        return globals;
    })()
    """
    
    resp = cdp_send(ws, "Runtime.evaluate", {
        "expression": script,
        "returnByValue": False,
        "includeCommandLineAPI": True
    }, msg_id=msg_id)
    msg_id += 1
    
    if "error" in resp or not resp["result"]["result"].get("objectId"):
        print("  Could not get global variables via script")
        return None, msg_id
    
    globals_obj_id = resp["result"]["result"]["objectId"]
    print(f"  Global variables objectId: {globals_obj_id}")
    
    # Get properties of the globals object
    globals_props = cdp_send(ws, "Runtime.getProperties", {
        "objectId": globals_obj_id,
        "ownProperties": True
    }, msg_id=msg_id)
    msg_id += 1
    
    return globals_props, msg_id

def get_lexical_scope_variables(ws, msg_id):
    """Get variables from global lexical scope."""
    print("\n=== Getting global lexical scope variables ===")
    
    try:
        # Get global lexical scope names
        resp = cdp_send(ws, "Runtime.globalLexicalScopeNames", {}, msg_id=msg_id)
        msg_id += 1
        
        if "error" not in resp and "result" in resp:
            names = resp["result"].get("names", [])
            print(f"  Found {len(names)} lexical scope variables")
            return names, msg_id
        else:
            print("  Could not get lexical scope names")
            return [], msg_id
    except Exception as e:
        print(f"  Error getting lexical scope: {e}")
        return [], msg_id

def get_storage_contents(ws, msg_id):
    """Get contents of cookies, sessionStorage, and localStorage."""
    print("\n=== Getting storage contents ===")
    
    storage_data = {
        "cookies": {},
        "sessionStorage": {},
        "localStorage": {}
    }
    
    # Get cookies via JavaScript (document.cookie)
    try:
        cookie_script = """
        (function() {
            const cookies = {};
            if (document.cookie) {
                document.cookie.split(';').forEach(cookie => {
                    const [name, ...rest] = cookie.trim().split('=');
                    if (name) {
                        cookies[name] = rest.join('=') || '';
                    }
                });
            }
            return cookies;
        })()
        """
        resp = cdp_send(ws, "Runtime.evaluate", {
            "expression": cookie_script,
            "returnByValue": True
        }, msg_id=msg_id)
        msg_id += 1
        
        if "error" not in resp and "result" in resp:
            cookies = resp["result"].get("result", {}).get("value", {})
            storage_data["cookies"] = cookies
            print(f"  Found {len(cookies)} cookies")
    except Exception as e:
        print(f"  Error getting cookies: {e}")
    
    # Get sessionStorage contents
    try:
        session_script = """
        (function() {
            const data = {};
            for (let i = 0; i < sessionStorage.length; i++) {
                const key = sessionStorage.key(i);
                if (key) {
                    try {
                        data[key] = sessionStorage.getItem(key);
                    } catch(e) {
                        data[key] = "<error reading value>";
                    }
                }
            }
            return data;
        })()
        """
        resp = cdp_send(ws, "Runtime.evaluate", {
            "expression": session_script,
            "returnByValue": True
        }, msg_id=msg_id)
        msg_id += 1
        
        if "error" not in resp and "result" in resp:
            session_data = resp["result"].get("result", {}).get("value", {})
            storage_data["sessionStorage"] = session_data
            print(f"  Found {len(session_data)} sessionStorage items")
    except Exception as e:
        print(f"  Error getting sessionStorage: {e}")
    
    # Get localStorage contents
    try:
        local_script = """
        (function() {
            const data = {};
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key) {
                    try {
                        data[key] = localStorage.getItem(key);
                    } catch(e) {
                        data[key] = "<error reading value>";
                    }
                }
            }
            return data;
        })()
        """
        resp = cdp_send(ws, "Runtime.evaluate", {
            "expression": local_script,
            "returnByValue": True
        }, msg_id=msg_id)
        msg_id += 1
        
        if "error" not in resp and "result" in resp:
            local_data = resp["result"].get("result", {}).get("value", {})
            storage_data["localStorage"] = local_data
            print(f"  Found {len(local_data)} localStorage items")
    except Exception as e:
        print(f"  Error getting localStorage: {e}")
    
    return storage_data, msg_id

def main():
    ws_url = get_ws_url()
    output_dir = Path("output_test")
    output_dir.mkdir(exist_ok=True)
    
    print("Connecting to:", ws_url)

    ws = create_connection(ws_url)
    time.sleep(0.2)

    msg_id = 1

    # Step 1: Get window object
    resp = cdp_send(ws, "Runtime.evaluate", {
        "expression": "window",
        "returnByValue": False
    }, msg_id=msg_id)
    msg_id += 1

    if "error" in resp or not resp["result"]["result"].get("objectId"):
        print("Window object not found!")
        ws.close()
        return

    window_obj = resp["result"]["result"]["objectId"]
    print(f"Window objectId: {window_obj}")

    # Step 1.5: Get global lexical scope variables
    lexical_vars, msg_id = get_lexical_scope_variables(ws, msg_id)
    
    # Step 1.6: Get global variables via JavaScript evaluation
    globals_props, msg_id = get_global_variables(ws, msg_id)
    
    # Step 1.7: Get storage contents (cookies, sessionStorage, localStorage)
    storage_data, msg_id = get_storage_contents(ws, msg_id)

    # Step 2: Get all properties of window (symbol table)
    print("\n=== Getting window symbol table ===")
    props = cdp_send(ws, "Runtime.getProperties", {
        "objectId": window_obj,
        "ownProperties": True
    }, msg_id=msg_id)
    msg_id += 1

    symbol_table = {
        "connection": ws_url,
        "window_objectId": window_obj,
        "properties": {},
        "lexical_scope_variables": lexical_vars,
        "global_variables_count": 0
    }
    
    object_files = []
    processed_names = set()  # Track which variables we've already processed
    source_tracking = {}  # Track where each variable came from: "window", "lexical", "additional_globals"
    
    # First, process lexical scope variables and add them to all_props
    lexical_props = []
    if lexical_vars:
        print(f"\n=== Processing {len(lexical_vars)} lexical scope variables ===")
        for var_name in lexical_vars:
            if var_name in processed_names:
                continue
            try:
                # Get the value of this variable
                eval_resp = cdp_send(ws, "Runtime.evaluate", {
                    "expression": var_name,
                    "returnByValue": False
                }, msg_id=msg_id)
                msg_id += 1
                
                if "error" not in eval_resp:
                    result = eval_resp["result"]["result"]
                    value_type = result.get("type", "unknown")
                    className = result.get("className", "")
                    
                    # Only process if not a native API
                    if not is_native_api(className, var_name):
                        # Create a prop-like structure
                        lexical_prop = {
                            "name": var_name,
                            "value": result,
                            "writable": True,  # Assume writable for lexical vars
                            "configurable": True,
                            "enumerable": True
                        }
                        lexical_props.append(lexical_prop)
                        processed_names.add(var_name)
                        source_tracking[var_name] = "lexical"
            except Exception as e:
                print(f"  Error processing lexical variable {var_name}: {e}")
        
        print(f"  Added {len(lexical_props)} lexical scope variables to processing queue")
    
    # Collect all properties to process
    all_props = list(props["result"]["result"])
    
    # Mark window properties
    for prop in all_props:
        source_tracking[prop.get("name")] = "window"
    
    # Add lexical scope variables
    all_props.extend(lexical_props)
    
    # Add global variables from JavaScript evaluation if available
    additional_globals_count = 0
    additional_global_names = []
    if globals_props and "result" in globals_props:
        global_props_list = globals_props["result"].get("result", [])
        print(f"\n=== Found {len(global_props_list)} additional global variables ===")
        for global_prop in global_props_list:
            prop_name = global_prop.get("name")
            if prop_name and prop_name not in processed_names:
                # Check if it's already in window props
                if not any(p.get("name") == prop_name for p in all_props):
                    all_props.append(global_prop)
                    processed_names.add(prop_name)
                    source_tracking[prop_name] = "additional_globals"
                    additional_global_names.append(prop_name)
                    additional_globals_count += 1
        print(f"  Added {additional_globals_count} new global variables to processing queue")
        if additional_global_names:
            print(f"  Additional global variable names: {', '.join(additional_global_names[:10])}{'...' if len(additional_global_names) > 10 else ''}")
    
    symbol_table["global_variables_count"] = additional_globals_count
    symbol_table["additional_global_variable_names"] = additional_global_names
    symbol_table["lexical_scope_variable_names"] = [v for v, src in source_tracking.items() if src == "lexical"]
    symbol_table["storage_contents"] = storage_data
    
    print(f"\n=== Processing {len(all_props)} total properties ===")
    
    skipped_count = 0
    processed_count = 0
    
    for prop in all_props:
        name = prop["name"]
        value = prop.get("value", {})
        value_type = value.get("type", "unknown")
        className = value.get("className", "")
        
        prop_info = {
            "type": value_type,
            "writable": prop.get("writable", False),
            "configurable": prop.get("configurable", False),
            "enumerable": prop.get("enumerable", False),
            "_source": source_tracking.get(name, "unknown")  # Track where this variable came from
        }
        
        # Use heuristic to determine if this is an application object
        is_app_object = is_application_object(className, name)
        
        # Special handling for storage APIs - they're native but we want to capture them
        # (they're already handled separately in get_storage_contents, but we include them here too)
        is_storage_api = name in ["sessionStorage", "localStorage", "cookieStore"]
        
        # Skip native browser APIs and circular references
        # Also skip functions that are native APIs (they don't have className in value)
        # BUT allow application objects and storage APIs even if they match other skip criteria
        should_skip = (
            not is_app_object and not is_storage_api and (
                is_native_api(className, name) or 
                name in ["window", "self", "top", "parent", "frames"] or
                (value_type == "function" and (name.startswith("HTML") or name.startswith("SVG") or 
                                               name.startswith("RTC") or name[0].isupper()))
            )
        )
        
        if should_skip:
            prop_info["_skipped"] = "Native API or circular reference"
            symbol_table["properties"][name] = prop_info
            skipped_count += 1
            if skipped_count % 100 == 0:
                print(f"  ... skipped {skipped_count} native APIs ...")
            continue
        
        if value_type == "string":
            prop_info["value"] = value.get("value")
            if processed_count % 100 == 0:
                print(f"  {name}: string")
        elif value_type in ["number", "boolean"]:
            prop_info["value"] = value.get("value")
            if processed_count % 100 == 0:
                print(f"  {name}: {value_type}")
        elif value_type == "object" and value.get("objectId"):
            obj_id = value.get("objectId")
            prop_info["objectId"] = obj_id
            prop_info["className"] = className
            prop_info["description"] = value.get("description", "")
            
            print(f"  {name}: object ({className}) - resolving...")
            
            # Fully resolve the object (only for non-native objects)
            resolved_obj = fully_resolve_object(ws, obj_id, max_depth=5)
            
            # Save to separate file
            safe_name = sanitize_filename(name)
            filename = output_dir / f"{safe_name}.json"
            
            obj_file_data = {
                "property_name": name,
                "className": className,
                "description": value.get("description", ""),
                "objectId": obj_id,
                "resolved_data": resolved_obj
            }
            
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(obj_file_data, f, indent=2, ensure_ascii=False)
            
            object_files.append({
                "name": name,
                "filename": f"{safe_name}.json",
                "className": className
            })
            
            print(f"    -> Saved to {filename}")
        elif value_type == "function":
            prop_info["description"] = value.get("description", "")
            if processed_count % 100 == 0:
                print(f"  {name}: function")
        else:
            prop_info["value"] = value.get("value")
            if processed_count % 100 == 0:
                print(f"  {name}: {value_type}")
        
        symbol_table["properties"][name] = prop_info
        processed_count += 1
    
    symbol_table["object_files"] = object_files
    
    # Save full symbol table
    symbol_table_path = output_dir / "symbol_table.json"
    with open(symbol_table_path, "w", encoding="utf-8") as f:
        json.dump(symbol_table, f, indent=2, ensure_ascii=False)
    
    # Create and save clean symbol table (without skipped items)
    clean_properties = {
        name: prop for name, prop in symbol_table["properties"].items()
        if "_skipped" not in prop
    }
    
    # Count variables by source in clean properties
    source_counts = {}
    for prop in clean_properties.values():
        source = prop.get("_source", "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
    
    symbol_table_clean = {
        "connection": symbol_table["connection"],
        "window_objectId": symbol_table["window_objectId"],
        "properties": clean_properties,
        "object_files": object_files,
        "additional_global_variable_names": symbol_table.get("additional_global_variable_names", []),
        "lexical_scope_variable_names": symbol_table.get("lexical_scope_variable_names", []),
        "variable_counts_by_source": source_counts,
        "storage_contents": storage_data
    }
    
    symbol_table_clean_path = output_dir / "symbol_table_clean.json"
    with open(symbol_table_clean_path, "w", encoding="utf-8") as f:
        json.dump(symbol_table_clean, f, indent=2, ensure_ascii=False)
    
    # Save storage contents to separate file
    storage_path = output_dir / "storage_contents.json"
    with open(storage_path, "w", encoding="utf-8") as f:
        json.dump(storage_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n=== Summary ===")
    print(f"Symbol table saved to: {symbol_table_path}")
    print(f"Clean symbol table saved to: {symbol_table_clean_path}")
    print(f"Storage contents saved to: {storage_path}")
    print(f"Total properties: {len(symbol_table['properties'])}")
    print(f"Clean properties: {len(symbol_table_clean['properties'])}")
    print(f"\nVariable sources:")
    print(f"  - Window properties: {source_counts.get('window', 0)}")
    print(f"  - Lexical scope variables: {len(symbol_table.get('lexical_scope_variable_names', []))}")
    print(f"  - Additional global variables: {len(symbol_table.get('additional_global_variable_names', []))}")
    if symbol_table.get('additional_global_variable_names'):
        print(f"\nAdditional global variable names:")
        for name in symbol_table['additional_global_variable_names'][:20]:
            print(f"  - {name}")
        if len(symbol_table['additional_global_variable_names']) > 20:
            print(f"  ... and {len(symbol_table['additional_global_variable_names']) - 20} more")
    print(f"\nStorage contents:")
    print(f"  - Cookies: {len(storage_data.get('cookies', {}))}")
    print(f"  - sessionStorage items: {len(storage_data.get('sessionStorage', {}))}")
    print(f"  - localStorage items: {len(storage_data.get('localStorage', {}))}")
    print(f"\nObject files created: {len(object_files)}")
    print(f"Skipped (native APIs): {skipped_count}")
    print(f"Output directory: {output_dir.absolute()}")
    
    ws.close()


if __name__ == "__main__":
    main()