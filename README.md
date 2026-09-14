# VanHix Via Tenting for Autodesk Fusion

Bulk-set solder mask (Auto, Off, Offset) for all vias on your open 2D PCB board in Autodesk Fusion with one click.

## Features
- **One-Click Via Tenting**: Quickly tent all vias (`Off`) or expose them (`Auto`) without manually editing each via.
- **Smart Grouping**: Group vias by Net, Drill Size, or Net & Drill to apply settings selectively.
- **Automatic DRC Solder Mask Limit**: Maintains `mlViaStopLimit` at 999 mil in Design Preferences for both Off and Auto modes.
- **Auto-Docking Palette**: Automatically docks cleanly to the right side of the PCB canvas using Fusion's native panel layout system (100% headless, zero cursor jumping).
- **Cross-Platform**: Fully compatible with both Windows and macOS.

## Installation

### Manual Installation (GitHub)
1. Download or clone this repository.
2. Copy the **`vanhix.ViaTenting.bundle`** folder into your Fusion AddIns directory:
   - **Windows**:
     ```text
     %appdata%\Autodesk\Autodesk Fusion 360\API\AddIns
     ```
     *(or `%appdata%\Autodesk\ApplicationPlugins`)*
   - **macOS**:
     ```text
     ~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns
     ```
     *(or `~/Library/Application Support/Autodesk/ApplicationPlugins`)*

3. In Autodesk Fusion, press `Shift + S` to open the **Scripts and Add-Ins** dialog.
4. Go to the **Add-Ins** tab, find **VanHix Via Tenting**, and click **Run**.
   *(Optional: check "Run on Startup" to load automatically with Fusion).*

## Usage
1. Open a **2D PCB Document** in Fusion Electronics.
2. In the toolbar, navigate to **UTILITIES** → **ADD-INS** → click **Via Tenting**.
3. The palette will open docked on the right side.
4. Select the desired solder mask mode (**Off** to tent, **Auto** to expose) and click **Apply to selected**.

## Support
For issues or questions, contact: [support@vanhix.com](mailto:support@vanhix.com).
