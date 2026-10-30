import json, pathlib, subprocess, sys, os
F='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FM='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
def duration(p):
 return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',p],text=True).strip())
def main():
 intro,body,app,poster,out = sys.argv[1:]
 i,b,ap=duration(intro),duration(body),duration(app)
 cut=11.6
 total=i+b-cut
 if not (110<total<180):raise SystemExit(f'Invalid total {total}; abort')
 if ap<65:raise SystemExit('Actual application footage too short')
 stamp=max(110,total-5.5)
 nv='fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p'
 filters=[
 f'[0:v]{nv},trim=duration={i:.3f},setpts=PTS-STARTPTS[iv]',
 f'[1:v]{nv},trim=start={cut:.3f},setpts=PTS-STARTPTS[bv]',
 '[0:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[ia]',
 f'[1:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,atrim=start={cut:.3f},asetpts=PTS-STARTPTS[ba]',
 '[iv][ia][bv][ba]concat=n=2:v=1:a=1[base][audio]',
 f"[base]drawbox=x=42:y=790:w=700:h=164:color=0x061426@0.73:t=fill:enable='between(t,1.5,7.8)',drawbox=x=42:y=790:w=10:h=164:color=0x34D0FF:t=fill:enable='between(t,1.5,7.8)',drawtext=fontfile={F}:text='Rafael López':x=80:y=816:fontsize=54:fontcolor=white:enable='between(t,1.5,7.8)',drawtext=fontfile={FM}:text='CEO  -  InnerChispa':x=85:y=896:fontsize=30:fontcolor=0x7CE8FF:enable='between(t,1.5,7.8)'[named]",
 f'[3:v]fps=30,scale=1920:1080,format=yuv420p,trim=duration=19,setpts=PTS-STARTPTS+14/TB[poster]',
 "[named][poster]overlay=x=0:y=0:eof_action=pass:enable='between(t,14,33)'[view1]",
 f"[4:v]drawtext=fontfile={F}:text='NEBIUS x NVIDIA':x=120:y=220:fontsize=82:fontcolor=white,drawtext=fontfile={F}:text='NEMOTRON 3 NANO':x=124:y=365:fontsize=64:fontcolor=0x63DAFF,drawtext=fontfile={FM}:text='RECORDED REAL MODEL RESPONSE':x=125:y=520:fontsize=37:fontcolor=0x87EED0,drawtext=fontfile={FM}:text='308 INPUT / 692 OUTPUT TOKENS':x=125:y=590:fontsize=34:fontcolor=white,drawtext=fontfile={FM}:text='Synthetic lab telemetry. No physical action.':x=125:y=720:fontsize=27:fontcolor=0xBDD2E4,format=yuv420p,trim=duration=12,setpts=PTS-STARTPTS+33/TB[model]",
 "[view1][model]overlay=x=0:y=0:eof_action=pass:enable='between(t,33,45)'[view2]",
 f'[2:v]{nv},trim=duration=65,setpts=PTS-STARTPTS+45/TB[appv]',
 "[view2][appv]overlay=x=0:y=0:eof_action=pass:enable='between(t,45,110)'[view3]",
 f"[5:v]drawtext=fontfile={F}:text='InnerChispa':x=128:y=245:fontsize=94:fontcolor=white,drawtext=fontfile={FM}:text='Cloud intelligence. Local authority.':x=135:y=405:fontsize=40:fontcolor=0x9BD8F3,drawtext=fontfile={F}:text='www.innerchispa.us':x=134:y=627:fontsize=66:fontcolor=0x54D4FF,format=yuv420p,trim=duration={total-stamp:.3f},setpts=PTS-STARTPTS+{stamp:.3f}/TB[ending]",
 f"[view3][ending]overlay=x=0:y=0:eof_action=pass:enable='between(t,{stamp:.3f},{total:.3f})'[v]",
 ]
 cmd=['ffmpeg','-hide_banner','-y','-loglevel','warning','-i',intro,'-i',body,'-i',app,'-loop','1','-framerate','30','-i',poster,'-f','lavfi','-i','color=c=0x061A33:s=1920x1080:r=30','-f','lavfi','-i','color=c=0x06132C:s=1920x1080:r=30','-filter_complex',';'.join(filters),'-map','[v]','-map','[audio]','-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart','-shortest',out]
 p=subprocess.run(cmd,text=True,capture_output=True)
 if p.returncode:raise SystemExit(p.stderr[-4500:])
 real=duration(out)
 assert real<180
 info={'seconds':real,'width':1920,'height':1080,'intro_original_seconds':i,'main_original_seconds':b,'main_cut_seconds':cut,'app_footage_seconds':65,'narration':'rafa english via ElevenLabs, existing licensed HeyGen avatar, 1.0x','main_visual_source':os.getenv('GUARDIAN_MAIN_VISUAL_MODE','corrected_lipsync'),'app_provenance':'Actual browser frames sampled at 1fps; synthetic telemetry; historical model receipt; dry-run actions; simulated recovery'}
 pathlib.Path(out+'.json').write_text(json.dumps(info,indent=2))
 print(json.dumps(info,indent=2))
if __name__=='__main__':main()
