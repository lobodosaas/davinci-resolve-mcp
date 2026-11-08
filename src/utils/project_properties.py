#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server - Project Properties Utilities

This module provides functions for working with DaVinci Resolve project properties:
- Getting and setting project settings
- Managing project metadata
- Handling project-specific configurations
"""

import os
import logging
import json
from typing import Dict, List, Any, Optional, Union

from src.utils.resolve_probe import has_method

# Configure logging
logger = logging.getLogger("davinci-resolve-mcp.project_properties")

# Common project properties with their types
PROJECT_PROPERTY_TYPES = {
    # Types of the values Resolve RETURNS from GetSetting (DaVinciResolveScript.pyi,
    # Resolve 21.1). SetSetting takes strings for every key here except superScale
    # (measured live: SetSetting("timelineResolutionWidth", 1920) -> False, "1920" -> True).
    # Timeline settings
    "timelineFrameRate": "float",
    "timelineResolutionWidth": "int",
    "timelineResolutionHeight": "int",
    "timelineOutputResolutionWidth": "int",
    "timelineOutputResolutionHeight": "int",
    "timelineInterlaceProcessing": "int",
    # Color settings
    "colorScienceMode": "string",
    "colorSpaceTimeline": "string",
    "colorSpaceTimelineGamma": "string",
    "separateColorSpaceAndGamma": "string",
    # Image processing
    "superScale": "int",
    # Cache / proxy / optimized media
    "perfRenderCacheMode": "string",
    "perfOptimisedMediaOn": "string",
    "perfProxyMediaMode": "string",
    "perfProxyResolutionRatio": "string",
    "perfOptimizedResolutionRatio": "string",
}

# Settings whose SetSetting value must keep a non-string type.
_NON_STRING_SETTINGS = {"superScale"}

def get_all_project_properties(project_obj) -> Dict[str, Any]:
    """
    Get all project properties and their values.
    
    Args:
        project_obj: Project object from DaVinci Resolve API
        
    Returns:
        Dictionary of all available project properties and their values
    """
    if project_obj is None:
        return {"error": "Invalid project object"}
    
    try:
        # Get all settings using empty string as key
        all_settings = project_obj.GetSetting('')
        
        # Check if we got a valid response
        if all_settings is None or not isinstance(all_settings, dict):
            logger.warning("GetSetting('') did not return expected dictionary")
            
            # Fall back to getting known properties individually
            properties = {}
            for prop_name in PROJECT_PROPERTY_TYPES.keys():
                try:
                    value = project_obj.GetSetting(prop_name)
                    properties[prop_name] = value
                except Exception as e:
                    logger.debug(f"Error getting property {prop_name}: {str(e)}")
            
            return properties
        else:
            # Return all settings
            return all_settings
            
    except Exception as e:
        logger.error(f"Error getting project properties: {str(e)}")
        return {"error": f"Error getting project properties: {str(e)}"}

def get_project_property(project_obj, property_name: str) -> Any:
    """
    Get a specific project property value.
    
    Args:
        project_obj: Project object from DaVinci Resolve API
        property_name: Name of the property to get
        
    Returns:
        Value of the specified property or error information
    """
    if project_obj is None:
        return {"error": "Invalid project object"}
    
    try:
        # Get the specified property
        value = project_obj.GetSetting(property_name)
        
        # Properly convert the value based on expected type
        if property_name in PROJECT_PROPERTY_TYPES:
            property_type = PROJECT_PROPERTY_TYPES[property_name]
            
            if property_type == "int" and not isinstance(value, int):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    # Keep Resolve's raw value when it cannot be safely coerced.
                    pass
            elif property_type == "float" and not isinstance(value, float):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    # Keep Resolve's raw value when it cannot be safely coerced.
                    pass
            elif property_type == "bool" and not isinstance(value, bool):
                # Convert string representations of boolean
                if isinstance(value, str):
                    value = value.lower() in ("true", "yes", "1", "on")
        
        return value
    except Exception as e:
        logger.error(f"Error getting project property {property_name}: {str(e)}")
        return {"error": f"Error getting project property: {str(e)}"}

def set_project_property(project_obj, property_name: str, property_value: Any) -> bool:
    """
    Set a project property value.
    
    Args:
        project_obj: Project object from DaVinci Resolve API
        property_name: Name of the property to set
        property_value: Value to set for the property
        
    Returns:
        True if successful, False otherwise
    """
    if project_obj is None:
        return False
    
    try:
        # Resolve's SetSetting takes strings ("Set as a string" in the 21.1 stub) for
        # every documented key except superScale; numbers and bools are refused.
        if property_name not in _NON_STRING_SETTINGS and not isinstance(property_value, str):
            if isinstance(property_value, bool):
                property_value = "1" if property_value else "0"
            elif isinstance(property_value, float) and property_value.is_integer():
                property_value = str(int(property_value))
            else:
                property_value = str(property_value)

        # Set the property
        return project_obj.SetSetting(property_name, property_value)
        
    except Exception as e:
        logger.error(f"Error setting project property {property_name}: {str(e)}")
        return False

def get_timeline_format_settings(project_obj) -> Dict[str, Any]:
    """
    Get timeline format settings for the project.
    
    Args:
        project_obj: Project object from DaVinci Resolve API
        
    Returns:
        Dictionary of timeline format settings
    """
    if project_obj is None:
        return {"error": "Invalid project object"}
    
    try:
        # Get relevant timeline format settings
        settings = {}
        format_properties = [
            "timelineFrameRate", 
            "timelineResolutionWidth", 
            "timelineResolutionHeight",
            "timelineOutputResolutionWidth",
            "timelineOutputResolutionHeight",
            "timelineInterlaceProcessing"
        ]
        
        for prop in format_properties:
            settings[prop] = get_project_property(project_obj, prop)
        
        # Add frame rate details
        if "timelineFrameRate" in settings:
            fps = settings["timelineFrameRate"]
            
            # Check if it's a drop frame rate
            is_drop_frame = False
            if isinstance(fps, (int, float)):
                # Common drop frame rates: 29.97, 59.94
                is_drop_frame = abs(fps - 29.97) < 0.01 or abs(fps - 59.94) < 0.01
            
            settings["isDropFrame"] = is_drop_frame
        
        # Add resolution name if standard
        if "timelineResolutionWidth" in settings and "timelineResolutionHeight" in settings:
            width = settings["timelineResolutionWidth"]
            height = settings["timelineResolutionHeight"]
            
            # Determine common resolution names
            resolution_name = None
            if width == 3840 and height == 2160:
                resolution_name = "UHD 4K"
            elif width == 1920 and height == 1080:
                resolution_name = "FHD 1080p"
            elif width == 1280 and height == 720:
                resolution_name = "HD 720p"
            elif width == 4096 and height in [2160, 2304]:
                resolution_name = "DCI 4K"
            elif width == 2048 and height in [1080, 1152]:
                resolution_name = "DCI 2K"
            
            if resolution_name:
                settings["resolutionName"] = resolution_name
        
        return settings
        
    except Exception as e:
        logger.error(f"Error getting timeline format settings: {str(e)}")
        return {"error": f"Error getting timeline format settings: {str(e)}"}

def set_timeline_format(project_obj, width: int, height: int, frame_rate: float, 
                       interlaced: bool = False) -> bool:
    """
    Set timeline format (resolution and frame rate).
    
    Args:
        project_obj: Project object from DaVinci Resolve API
        width: Timeline width in pixels
        height: Timeline height in pixels
        frame_rate: Timeline frame rate
        interlaced: Whether the timeline should use interlaced processing
        
    Returns:
        True if successful, False otherwise
    """
    if project_obj is None:
        return False
    
    try:
        # Set timeline format properties
        success = True
        
        # Set resolution
        if not set_project_property(project_obj, "timelineResolutionWidth", width):
            success = False
        
        if not set_project_property(project_obj, "timelineResolutionHeight", height):
            success = False
        
        # Set frame rate
        if not set_project_property(project_obj, "timelineFrameRate", frame_rate):
            success = False
        
        # Set interlaced processing
        interlace_value = 1 if interlaced else 0
        if not set_project_property(project_obj, "timelineInterlaceProcessing", interlace_value):
            success = False
        
        return success
        
    except Exception as e:
        logger.error(f"Error setting timeline format: {str(e)}")
        return False

def get_superscale_settings(project_obj) -> Dict[str, Any]:
    """
    Get SuperScale settings for the project.
    
    Args:
        project_obj: Project object from DaVinci Resolve API
        
    Returns:
        Dictionary of SuperScale settings
    """
    if project_obj is None:
        return {"error": "Invalid project object"}
    
    try:
        # Get SuperScale settings
        settings = {}
        
        value = project_obj.GetSetting("superScale")
        settings["superScale"] = value
        settings["enabled"] = value not in (1, None)
        settings["scaleName"] = {0: "Auto", 1: "none", 2: "2x", 3: "3x", 4: "4x"}.get(value, "unknown")
        for prop in ["superScaleSharpness", "superScaleNoiseReduction"]:
            v = project_obj.GetSetting(prop)
            if v is not None:
                settings[prop] = v
        
        return settings
        
    except Exception as e:
        logger.error(f"Error getting SuperScale settings: {str(e)}")
        return {"error": f"Error getting SuperScale settings: {str(e)}"}

def set_superscale_settings(project_obj, enabled: bool, quality: int = 0) -> bool:
    """Set the project SuperScale multiplier (native ``superScale``, an int).

    Resolve 21.1 values: 0=Auto, 1=none, 2=2x, 3=3x, 4=4x. ``enabled=False`` writes 1.
    ``quality`` is the multiplier to apply when enabled (0, 2, 3 or 4); the older
    0/1/2 "quality" meaning never existed as a Resolve setting.
    """
    if project_obj is None:
        return False
    value = int(quality) if enabled else 1
    if enabled and value not in (0, 2, 3, 4):
        return False
    try:
        return bool(project_obj.SetSetting("superScale", value)) and project_obj.GetSetting("superScale") == value
    except Exception as e:
        logger.error(f"Error setting SuperScale settings: {str(e)}")
        return False


def get_color_settings(project_obj) -> Dict[str, Any]:
    """
    Get color science and color space settings for the project.
    
    Args:
        project_obj: Project object from DaVinci Resolve API
        
    Returns:
        Dictionary of color settings
    """
    if project_obj is None:
        return {"error": "Invalid project object"}
    
    try:
        # Get color-related settings
        settings = {}
        color_properties = [
            "colorScienceMode",
            "colorSpaceTimeline",
            "colorSpaceTimelineGamma",
            "separateColorSpaceAndGamma",
        ]
        
        for prop in color_properties:
            value = get_project_property(project_obj, prop)
            if value is not None:
                settings[prop] = value
        
        # Translate colorScienceMode to descriptive name
        if "colorScienceMode" in settings:
            mode = settings["colorScienceMode"]
            mode_names = {
                "davinciYRGB": "DaVinci YRGB",
                "davinciYRGBColorManaged": "DaVinci YRGB Color Managed (legacy)",
                "davinciYRGBColorManagedv2": "DaVinci YRGB Color Managed",
                "acescc": "ACEScc",
                "acescct": "ACEScct",
            }
            
            if mode in mode_names:
                settings["colorScienceName"] = mode_names[mode]
        
        return settings
        
    except Exception as e:
        logger.error(f"Error getting color settings: {str(e)}")
        return {"error": f"Error getting color settings: {str(e)}"}

COLOR_SCIENCE_MODES = {
    # aliases accepted by this server -> native colorScienceMode values (21.1 stub)
    "YRGB": "davinciYRGB",
    "DaVinci YRGB": "davinciYRGB",
    "YRGB Color Managed": "davinciYRGBColorManagedv2",
    "DaVinci YRGB Color Managed": "davinciYRGBColorManagedv2",
    "ACEScct": "acescct",
    "ACEScc": "acescc",
    "ACES": "acescct",
}
NATIVE_COLOR_SCIENCE_MODES = ("davinciYRGB", "davinciYRGBColorManaged",
                              "davinciYRGBColorManagedv2", "acescc", "acescct")


def set_color_science_mode(project_obj, mode: str) -> bool:
    """Set color science mode. Accepts native values or the aliases in COLOR_SCIENCE_MODES."""
    if project_obj is None:
        return False
    native = mode if mode in NATIVE_COLOR_SCIENCE_MODES else COLOR_SCIENCE_MODES.get(str(mode))
    if native is None:
        logger.error(f"Invalid color science mode: {mode}")
        return False
    try:
        return bool(project_obj.SetSetting("colorScienceMode", native)) and project_obj.GetSetting("colorScienceMode") == native
    except Exception as e:
        logger.error(f"Error setting color science mode: {str(e)}")
        return False


def set_color_space(project_obj, color_space: str, gamma: str = None) -> bool:
    """Set timeline color space (``colorSpaceTimeline``) and optional gamma
    (``colorSpaceTimelineGamma``, which needs ``separateColorSpaceAndGamma`` = '1').
    Values are the names shown in Project Settings, e.g. 'Rec.709 (Scene)'."""
    if project_obj is None:
        return False
    try:
        if gamma is not None:
            if not project_obj.SetSetting("separateColorSpaceAndGamma", "1"):
                return False
        if not project_obj.SetSetting("colorSpaceTimeline", str(color_space)):
            return False
        if gamma is not None and not project_obj.SetSetting("colorSpaceTimelineGamma", str(gamma)):
            return False
        return True
    except Exception as e:
        logger.error(f"Error setting color space: {str(e)}")
        return False


def get_project_metadata(project_obj) -> Dict[str, Any]:
    """
    Get project metadata.
    
    Args:
        project_obj: Project object from DaVinci Resolve API
        
    Returns:
        Dictionary of project metadata
    """
    if project_obj is None:
        return {"error": "Invalid project object"}
    
    try:
        metadata = {}
        
        # Add basic project info
        metadata["name"] = project_obj.GetName()
        
        # Add project path if available
        if has_method(project_obj, "GetPath"):
            metadata["path"] = project_obj.GetPath()
        
        # Get current timeline
        current_timeline = project_obj.GetCurrentTimeline()
        if current_timeline:
            metadata["currentTimeline"] = current_timeline.GetName()
            
            # Add timeline count
            timeline_count = project_obj.GetTimelineCount()
            metadata["timelineCount"] = timeline_count
        
        # Add frame rate and resolution
        format_settings = get_timeline_format_settings(project_obj)
        if "error" not in format_settings:
            metadata.update(format_settings)
        
        # Add color settings
        color_settings = get_color_settings(project_obj)
        if "error" not in color_settings:
            metadata["colorSettings"] = color_settings
        
        # Add SuperScale settings
        superscale_settings = get_superscale_settings(project_obj)
        if "error" not in superscale_settings:
            metadata["superScale"] = superscale_settings
        
        return metadata
        
    except Exception as e:
        logger.error(f"Error getting project metadata: {str(e)}")
        return {"error": f"Error getting project metadata: {str(e)}"}

def get_project_info(project_obj) -> Dict[str, Any]:
    """
    Get comprehensive project information including settings and metadata.
    
    Args:
        project_obj: Project object from DaVinci Resolve API
        
    Returns:
        Dictionary with project information
    """
    if project_obj is None:
        return {"error": "Invalid project object"}
    
    try:
        # Get project name
        project_name = project_obj.GetName()
        
        # Combine all project information
        project_info = {
            "name": project_name,
            "metadata": get_project_metadata(project_obj),
            "settings": get_all_project_properties(project_obj),
            "timelines": []
        }
        
        # Add timeline information
        timeline_count = project_obj.GetTimelineCount()
        current_timeline = project_obj.GetCurrentTimeline()
        current_timeline_name = current_timeline.GetName() if current_timeline else None
        
        for i in range(1, timeline_count + 1):
            timeline = project_obj.GetTimelineByIndex(i)
            if timeline:
                timeline_info = {
                    "name": timeline.GetName(),
                    "isCurrent": timeline.GetName() == current_timeline_name,
                    "duration": timeline.GetEndFrame() - timeline.GetStartFrame()
                }
                project_info["timelines"].append(timeline_info)
        
        return project_info
        
    except Exception as e:
        logger.error(f"Error getting project info: {str(e)}")
        return {"error": f"Error getting project info: {str(e)}"}
