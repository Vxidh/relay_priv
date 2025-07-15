# File: remote_control_app/views.py
from django.shortcuts import render
import logging

logger = logging.getLogger(__name__)

def remote_control_viewer_page(request):
    """
    Renders the HTML page for the remote control viewer.
    """
    logger.info("Serving remote_control_viewer_page HTML.")
    return render(request, 'remote_control_app/remote_control_viewer.html', {})