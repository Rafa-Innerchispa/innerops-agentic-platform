"""Pipeline de vídeo RalfIA — TTS, montaje ffmpeg, publicación."""

from raphiia_openai.video_pipeline.pipeline import generate_video, pipeline_health

__all__ = ["generate_video", "pipeline_health"]
