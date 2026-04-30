import os
import subprocess
import tempfile
import uuid
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = tempfile.gettempdir()

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

FORMAT_SIZES = {
    '9:16': (1080, 1920),
    '4:5': (1080, 1350),
    '1:1': (1080, 1080),
    '16:9': (1920, 1080),
}

def get_duration(path):
    result = subprocess.run([
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        path
    ], capture_output=True, text=True)

    if result.returncode != 0:
        return 1

    try:
        return max(float(result.stdout.strip()), 1)
    except Exception:
        return 1

def has_audio(path):
    result = subprocess.run([
        'ffprobe', '-v', 'error',
        '-select_streams', 'a',
        '-show_entries', 'stream=index',
        '-of', 'csv=p=0',
        path
    ], capture_output=True, text=True)

    return bool(result.stdout.strip())

def get_video_size(path):
    result = subprocess.run([
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height',
        '-of', 'csv=s=x:p=0',
        path
    ], capture_output=True, text=True)

    if result.returncode != 0:
        return 1080, 1920

    try:
        width, height = result.stdout.strip().split('x')
        return int(width), int(height)
    except Exception:
        return 1080, 1920

def get_output_size(output_format, reference_video_path):
    if output_format in FORMAT_SIZES:
        return FORMAT_SIZES[output_format]

    ref_width, ref_height = get_video_size(reference_video_path)
    ref_ratio = ref_width / ref_height if ref_height else 9 / 16

    candidates = {
        '9:16': 9 / 16,
        '4:5': 4 / 5,
        '1:1': 1,
        '16:9': 16 / 9,
    }

    closest_format = min(
        candidates.keys(),
        key=lambda key: abs(candidates[key] - ref_ratio)
    )

    return FORMAT_SIZES[closest_format]

def normalize_video(input_path, output_path, target_width, target_height):
    duration = get_duration(input_path)

    video_filter = (
        f'scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,'
        f'pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,'
        'fps=30,setsar=1'
    )

    base_video_options = [
        '-vf', video_filter,
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '24',
        '-pix_fmt', 'yuv420p',
        '-threads', '1',
    ]

    audio_options = [
        '-c:a', 'aac',
        '-b:a', '128k',
        '-ar', '44100',
        '-ac', '2',
        '-shortest',
        '-movflags', '+faststart',
        output_path
    ]

    if has_audio(input_path):
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-map', '0:v:0',
            '-map', '0:a:0',
            *base_video_options,
            *audio_options
        ]
    else:
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-f', 'lavfi',
            '-t', str(duration),
            '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
            '-map', '0:v:0',
            '-map', '1:a:0',
            *base_video_options,
            *audio_options
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(result.stderr)

@app.route('/combine', methods=['POST'])
def combine():
    try:
        if 'hook' not in request.files or 'content' not in request.files or 'cta' not in request.files:
            return jsonify({'error': 'Missing files. Need: hook, content, cta'}), 400

        output_format = request.form.get('format', 'auto').strip()

        if output_format not in ['auto', '9:16', '4:5', '1:1', '16:9']:
            output_format = 'auto'

        job_id = str(uuid.uuid4())[:8]
        tmp = tempfile.mkdtemp()

        hook_path = os.path.join(tmp, 'hook.mp4')
        content_path = os.path.join(tmp, 'content.mp4')
        cta_path = os.path.join(tmp, 'cta.mp4')

        hook_norm = os.path.join(tmp, 'hook_norm.mp4')
        content_norm = os.path.join(tmp, 'content_norm.mp4')
        cta_norm = os.path.join(tmp, 'cta_norm.mp4')

        list_path = os.path.join(tmp, 'list.txt')
        out_path = os.path.join(tmp, f'output_{job_id}.mp4')

        request.files['hook'].save(hook_path)
        request.files['content'].save(content_path)
        request.files['cta'].save(cta_path)

        target_width, target_height = get_output_size(output_format, hook_path)

        normalize_video(hook_path, hook_norm, target_width, target_height)
        normalize_video(content_path, content_norm, target_width, target_height)
        normalize_video(cta_path, cta_norm, target_width, target_height)

        with open(list_path, 'w', encoding='utf-8') as f:
            f.write(f"file '{hook_norm}'\n")
            f.write(f"file '{content_norm}'\n")
            f.write(f"file '{cta_norm}'\n")

        result = subprocess.run([
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', list_path,
            '-c', 'copy',
            '-movflags', '+faststart',
            out_path
        ], capture_output=True, text=True)

        if result.returncode != 0:
            return jsonify({'error': 'FFmpeg concat failed', 'details': result.stderr}), 500

        return send_file(
            out_path,
            mimetype='video/mp4',
            as_attachment=True,
            download_name=f'video_{job_id}.mp4'
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
