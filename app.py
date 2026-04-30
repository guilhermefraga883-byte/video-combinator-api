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


def get_duration(path):
    """
    Returns the duration of a media file in seconds.
    Used only to create silent audio when a video has no audio track.
    """
    result = subprocess.run([
        'ffprobe',
        '-v', 'error',
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
    """
    Checks whether the uploaded video has an audio stream.
    """
    result = subprocess.run([
        'ffprobe',
        '-v', 'error',
        '-select_streams', 'a',
        '-show_entries', 'stream=index',
        '-of', 'csv=p=0',
        path
    ], capture_output=True, text=True)

    return bool(result.stdout.strip())


def normalize_video(input_path, output_path):
    """
    Converts each video separately to the same format before joining.
    This uses much less memory on Render Free than processing all videos at once.
    """
    duration = get_duration(input_path)

    if has_audio(input_path):
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-map', '0:v:0',
            '-map', '0:a:0',
            '-vf',
            'scale=720:1280:force_original_aspect_ratio=decrease,'
            'pad=720:1280:(ow-iw)/2:(oh-ih)/2,'
            'fps=30,setsar=1',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '28',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            '-b:a', '96k',
            '-ar', '44100',
            '-ac', '2',
            '-shortest',
            '-movflags', '+faststart',
            output_path
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
            '-vf',
            'scale=720:1280:force_original_aspect_ratio=decrease,'
            'pad=720:1280:(ow-iw)/2:(oh-ih)/2,'
            'fps=30,setsar=1',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '28',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            '-b:a', '96k',
            '-ar', '44100',
            '-ac', '2',
            '-shortest',
            '-movflags', '+faststart',
            output_path
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(result.stderr)


@app.route('/combine', methods=['POST'])
def combine():
    """
    Expects multipart/form-data with:
      - hook: video file
      - content: video file
      - cta: video file

    Returns: combined MP4 file.
    """
    try:
        if 'hook' not in request.files or 'content' not in request.files or 'cta' not in request.files:
            return jsonify({'error': 'Missing files. Need: hook, content, cta'}), 400

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

        # Normalize one video at a time to avoid Render Free memory limit.
        normalize_video(hook_path, hook_norm)
        normalize_video(content_path, content_norm)
        normalize_video(cta_path, cta_norm)

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
