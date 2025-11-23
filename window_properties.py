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

def cdp_send(ws, method, params=None, msg_id=1):
    payload = {"id": msg_id, "method": method}
    if params:
        payload["params"] = params
    ws.send(json.dumps(payload))
    return json.loads(ws.recv())

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
    
    # If className is "Object" or empty, only treat as application object if name is lowercase
    # (native APIs usually have uppercase names)
    if className == "Object" or not className:
        if name and name[0].islower() and name[0].isalpha():
            return True
        # Default to native if we're not sure
        return False
    
    # If we get here and className doesn't match native patterns, it might be application
    # But be conservative - only if it's clearly not native
    return True

def fully_resolve_object_flat(ws, object_id, base_path, flat_dict, visited=None, depth=0, max_depth=10):
    """
    Recursively resolve an object and add all properties to a flat dictionary with dot paths.
    """
    if visited is None:
        visited = set()
    
    if depth > max_depth or object_id in visited:
        return
    
    visited.add(object_id)
    
    try:
        props = cdp_send(ws, "Runtime.getProperties", {
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
                        fully_resolve_object_flat(ws, nested_obj_id, prop_path, flat_dict, visited.copy(), depth + 1, max_depth)
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

def main():
    ws_url = get_ws_url()
    output_dir = Path("output")
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

    # Get all properties of window
    print("\n=== Getting window properties ===")
    props = cdp_send(ws, "Runtime.getProperties", {
        "objectId": window_obj,
        "ownProperties": True
    }, msg_id=msg_id)
    msg_id += 1

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
        # Also skip functions that are native APIs (they don't have className in value)
        # BUT allow application objects and storage APIs even if they match other skip criteria
        should_skip = (
            not is_app_object and (
                value_type == "function" and (name.startswith("HTML") or name.startswith("SVG") or 
                                             name.startswith("RTC") or name[0].isupper())
            )
        )
        
        if should_skip:
            skipped_count += 1
            if skipped_count % 100 == 0:
                print(f"  ... skipped {skipped_count} native APIs ...")
            continue
        
        # Only store actual values, no metadata
        if value_type == "string":
            flat_dict[name] = value.get("value")
            if processed_count % 100 == 0:
                print(f"  {name}: string")
        elif value_type in ["number", "boolean"]:
            flat_dict[name] = value.get("value")
            if processed_count % 100 == 0:
                print(f"  {name}: {value_type}")
        elif value_type == "object" and value.get("objectId"):
            obj_id = value.get("objectId")
            
            print(f"  {name}: object ({className}) - resolving...")
            
            # Fully resolve the object into flat dict (only for non-native objects)
            # Use higher max_depth to ensure we capture deeply nested application objects
            fully_resolve_object_flat(ws, obj_id, name, flat_dict, max_depth=10)
            
            print(f"    -> Resolved {name}")
        elif value_type == "function":
            # Skip functions - don't add anything
            if processed_count % 100 == 0:
                print(f"  {name}: function")
        else:
            flat_dict[name] = value.get("value")
            if processed_count % 100 == 0:
                print(f"  {name}: {value_type}")
        
        processed_count += 1
    
    # Save the flat dictionary to a single file
    output_file = output_dir / "window_properties_flat.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(flat_dict, f, indent=2, ensure_ascii=False)
    
    print(f"\n=== Summary ===")
    print(f"Flat properties file saved to: {output_file}")
    print(f"Total properties in flat dict: {len(flat_dict)}")
    print(f"Processed properties: {processed_count}")
    print(f"Skipped (native APIs): {skipped_count}")
    print(f"Output directory: {output_dir.absolute()}")
    
    ws.close()


if __name__ == "__main__":
    main()