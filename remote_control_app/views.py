# remote_control_app/views.py
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render

@csrf_exempt
def remote_control_entry(request):
    # UI for entering node-id
    if request.method == 'GET':
        return render(request, 'remote_control_app/remote_control.html')
    return JsonResponse({'error': 'Invalid method'}, status=405)

@csrf_exempt
def start_remote_control(request):
    # Logic for starting remote control (dummy for now)
    return JsonResponse({'status': 'success'})

@csrf_exempt
def stream_images(request, node_id):
    # Dummy streaming endpoint
    def image_stream():
        while True:
            # Yield dummy image data
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + b'' + b'\r\n'
    return StreamingHttpResponse(image_stream(), content_type='multipart/x-mixed-replace; boundary=frame')
