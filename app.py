import os
import subprocess
import tempfile
import uuid
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow all origins

UPLOAD_FOLDER = tempfile.gettempdir()

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/combine', methods=['POST'])
def combine():
    """
    Expects multipart/form-data with:
      - hook: video file
      - content: video file
      - cta: video file
    Returns: combined MP4 file
    """
    try:
        if 'hook' not in request.files or 'content' not in request.files or 'cta' not in request.files:
            return jsonify({'error': 'Missing files. Need: hook, content, cta'}), 400

        job_id = str(uuid.uuid4())[:8]
        tmp = tempfile.mkdtemp()

        hook_path    = os.path.join(tmp, 'hook.mp4')
        content_path = os.path.join(tmp, 'content.mp4')
        cta_path     = os.path.join(tmp, 'cta.mp4')
        list_path    = os.path.join(tmp, 'list.txt')
        out_path     = os.path.join(tmp, f'output_{job_id}.mp4')

        request.files['hook'].save(hook_path)
        request.files['content'].save(content_path)
        request.files['cta'].save(cta_path)

        with open(list_path, 'w') as f:
            f.write(f"file '{hook_path}'\n")
            f.write(f"file '{content_path}'\n")
            f.write(f"file '{cta_path}'\n")

        result = subprocess.run([
    'ffmpeg', '-y',
    '-i', hook_path,
    '-i', content_path,
    '-i', cta_path,
    '-filter_complex',
    '[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1[v0];'
    '[1:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1[v1];'
    '[2:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1[v2];'
    '[0:a]aresample=44100[a0];'
    '[1:a]aresample=44100[a1];'
    '[2:a]aresample=44100[a2];'
    '[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[outv][outa]',
    '-map', '[outv]',
    '-map', '[outa]',
    '-c:v', 'libx264',
    '-preset', 'fast',
    '-crf', '23',
    '-pix_fmt', 'yuv420p',
    '-c:a', 'aac',
    '-b:a', '128k',
    '-movflags', '+faststart',
    out_path
], capture_output=True, text=True)

        if result.returncode != 0:
            return jsonify({'error': 'FFmpeg failed', 'details': result.stderr}), 500

        return send_file(out_path, mimetype='video/mp4', as_attachment=True,
                         download_name=f'video_{job_id}.mp4')

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
