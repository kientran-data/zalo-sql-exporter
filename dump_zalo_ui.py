import sys
import codecs
from pywinauto import Desktop

def dump_zalo_ui():
    print("Listing top-level windows to find Zalo...")
    try:
        # Use UIA backend as it's the standard for modern Windows apps (Electron, Chromium, WPF, etc.)
        desktop = Desktop(backend="uia")
        windows = desktop.windows()
        zalo_win = None
        
        for w in windows:
            title = w.window_text()
            if title and "Zalo" in title:
                print(f"Found potential Zalo window: '{title}' (Handle: {w.handle})")
                zalo_win = w
                break # We just take the first one that matches
                
        if not zalo_win:
            print("Could not find any window with 'Zalo' in the title.")
            print("Please ensure Zalo PC is running and you are logged in.")
            return

        output_file = "zalo_ui_tree.txt"
        print(f"\nAttempting to dump window control identifiers to {output_file}...")
        
        from pywinauto import Application
        app = Application(backend="uia").connect(handle=zalo_win.handle)
        dlg = app.top_window()
        import codecs
        from contextlib import redirect_stdout
        
        with codecs.open(output_file, "w", encoding="utf-8") as f:
            with redirect_stdout(f):
                dlg.print_control_identifiers(depth=8)
                
        print(f"Successfully saved UI tree to {output_file}")
        print("Please check this file to see if message content, sender, and time are readable.")

    except Exception as e:
        print(f"Failed to inspect Zalo UI.")
        print(f"Error: {e}")

if __name__ == "__main__":
    dump_zalo_ui()
