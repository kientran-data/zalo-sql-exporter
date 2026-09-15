import sys
from pywinauto import Desktop
from pywinauto.application import Application

def inspect_zalo():
    print("Listing top-level windows to find Zalo...")
    try:
        desktop = Desktop(backend="uia")
        windows = desktop.windows()
        zalo_win = None
        for w in windows:
            title = w.window_text()
            if "Zalo" in title:
                print(f"Found potential Zalo window: '{title}' (Handle: {w.handle})")
                zalo_win = w
                
        if not zalo_win:
            print("Could not find any window with 'Zalo' in the title.")
            return

        print("\nAttempting to dump window control identifiers (depth=2)...")
        # Just getting the first few levels to avoid massive output
        try:
            zalo_win.dump_tree(depth=3)
        except Exception as e:
            print(f"Error dumping tree: {e}")

    except Exception as e:
        print(f"Failed to access desktop or windows. This often happens if the script is not running in the same desktop session as the UI. Error: {e}")

if __name__ == "__main__":
    inspect_zalo()
