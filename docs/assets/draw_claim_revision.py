# 文件圖稿；來源為 core/belief.py、authority.py、escalation.py、repositories/reviews.py。
# 本檔不評估科學假說；例子為 tests/contract 的 toy policies，並非研究成果。
# 執行本檔檢查英文標籤、版面與文字重疊，再匯出 SVG/PNG。
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch,FancyArrowPatch,Polygon
plt.rcParams.update({'font.family':'DejaVu Sans','svg.fonttype':'none','svg.hashsalt':'lib-claim-revision-v1'})
fig,ax=plt.subplots(figsize=(16,8),dpi=160); fig.subplots_adjust(0,0,1,1)
ax.set(xlim=(0,16),ylim=(0,8)); ax.axis('off'); fig.patch.set_facecolor('#FAFBFD')
ink,muted,blue,teal,amber='#193048','#56697D','#2C62A2','#197B76','#A46D25'
texts=[]
def t(x,y,s,size=14,c=ink,b=False,ha='left'):
    assert s.isascii(); texts.append(ax.text(x,y,s,fontsize=size,color=c,fontweight='bold' if b else 'normal',ha=ha,va='center',linespacing=1.45))
def box(x,y,w,h,fc='white',ec='#CAD6E2'):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=.02,rounding_size=.14',fc=fc,ec=ec,lw=1.4))
def arr(a,b,c=blue,dash=False): ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-|>',mutation_scale=17,lw=2,color=c,ls='--' if dash else '-'))
t(.65,7.4,'LABORATORY INNOVATION BRAIN  /  CLAIM REVISION',12,blue,True)
t(.65,6.85,'Keep the reason behind a scientific claim',25,ink,True)
t(.65,6.25,'Toy example: a proposed claim update must pass evidence and policy checks.',14,muted)
box(.65,3.65,3.05,1.92,'#EFF5FC','#ABC3DF')
t(.96,5.14,'Evidence + claim',18,ink,True)
t(.96,4.48,'Source locator\nObserved conditions\nProposed state change',13,muted)
arr((3.7,4.62),(4.3,4.62))
box(4.3,3.65,3.35,1.92)
t(4.63,5.13,'Check the links',18,ink,True)
t(4.63,4.47,'Support / contradiction\nSource independence\nEvidence authority',13,muted)
arr((7.65,4.62),(8.17,4.62))
ax.add_patch(Polygon([(8.17,4.62),(9.38,5.56),(10.59,4.62),(9.38,3.68)],fc='#EAF5F2',ec=teal,lw=1.6))
t(9.38,4.83,'Policy',18,teal,True,'center'); t(9.38,4.38,'decision',14,teal,False,'center')
arr((10.59,4.62),(11.5,4.62),teal)
t(11.04,4.94,'Allow',12,teal,ha='center')
box(11.5,3.57,3.84,2.0,'#EAF5F2','#A8CEC7')
t(11.84,5.12,'Revision record',18,ink,True)
t(11.84,4.45,'Before / after state\nPolicy + source links\nReplayable event history',13,muted)
arr((9.38,3.68),(9.38,2.95),amber,True)
box(7.54,1.55,3.69,1.36,'#FFF5E7','#E0C195')
t(9.38,2.52,'Human review',17,amber,True,'center')
t(9.38,1.98,'Unresolved conflict blocks change',11,muted,ha='center')
ax.plot([7.54,6,6],[2.2,2.2,3.1],color=amber,lw=2,ls='--')
arr((6,3.1),(6,3.65),amber,True)
t(5.83,1.35,'Resolve, then reconsider',12,amber,ha='center')
box(11.85,1.55,3.5,1.36,'#F1F3F6','#C6CFD9')
t(13.6,2.48,'No accepted update',16,ink,True,'center')
t(13.6,1.98,'Denied / insufficient evidence',11,muted,ha='center')
arr((10.43,3.95),(12,2.95),muted)
t(.7,2.4,'OUTPUT: A TRACEABLE DECISION',12,teal,True)
t(.7,1.94,'A model response alone cannot change a claim.',12,ink)
ax.plot([.65,15.35],[.85,.85],color='#CAD6E2',lw=1)
t(.65,.44,'Implemented core only. Paper ingestion, domain applications, simulator integration and a dashboard are planned.',12,muted)
fig.canvas.draw();ren=fig.canvas.get_renderer();bb=[x.get_window_extent(ren) for x in texts]
for b in bb: assert fig.bbox.contains(b.x0,b.y0) and fig.bbox.contains(b.x1,b.y1)
for i,b in enumerate(bb):
    for j,c in enumerate(bb[:i]): assert not b.overlaps(c),(texts[i].get_text(),texts[j].get_text())
out=Path(__file__).resolve().parent
fig.savefig(out/'claim-revision.png',dpi=180); fig.savefig(out/'claim-revision.svg',metadata={'Date':None})
p=out/'claim-revision.svg';p.write_text('\n'.join(l.rstrip() for l in p.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8')
print('English labels, bounds and overlap checks passed.')
