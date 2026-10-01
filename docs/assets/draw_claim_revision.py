# 文件圖稿：核對 test_transition_policy.py 與 test_belief_transition.py。
# Toy claim/evidence/policy 示意；不是科研結論、paper ingestion 或 DomainPack。
# 執行本檔匯出 SVG/PNG；檢查英文文字、字體、邊界與重疊。
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle,FancyArrowPatch
plt.rcParams.update({'font.family':'DejaVu Sans','svg.fonttype':'none','svg.hashsalt':'lib-v04'})
fig,ax=plt.subplots(figsize=(6,8.5),dpi=160);fig.subplots_adjust(0,0,1,1)
ax.set(xlim=(0,6),ylim=(0,8.5));ax.axis('off')
ink,teal,amber,red='#18324B','#087F83','#995719','#A34334'
def t(y,s,size=18,c=ink,b=False):
    assert s.isascii()
    ax.text(3,y,s,fontsize=size,color=c,weight='bold' if b else 'normal',ha='center',va='center',linespacing=1.35)
t(8.12,'What can change a claim?',24,b=True)
t(7.65,'Toy claim H: ACTIVE',20,b=True)
t(7.22,'Request: change H to SUPPORTED')
t(6.79,'Versioned policy evaluates evidence')
for top,fill,color,condition,outcome in [
 (6.30,'#E7F4F1',teal,'Support + 2 independent attestations','ALLOW'),
 (4.82,'#FFF2DE',amber,'No admitted support relation','NEED_MORE_EVIDENCE'),
 (3.34,'#FFF0E8',red,'Open blocking conflict','NEED_HUMAN_REVIEW')]:
    ax.add_patch(Rectangle((.35,top-1.18),5.3,1.18,fc=fill,ec=color,lw=1.4))
    t(top-.31,condition,c=color)
    t(top-.81,outcome,20,c=color,b=True)
t(1.75,'Only ALLOW can record a revision',20,c=teal,b=True)
ax.add_patch(FancyArrowPatch((3,1.52),(3,1.15),arrowstyle='-|>',mutation_scale=15,color=teal,lw=1.7))
t(1.06,'State + source links + policy reason',c=teal)
t(.63,'Refused changes leave state unchanged')
t(.23,'Core fixture; lab applications planned',c=amber)
fig.canvas.draw();ren=fig.canvas.get_renderer();bounds=[]
for label in ax.texts:
    assert label.get_fontsize()>=18
    box=label.get_window_extent(ren)
    assert fig.bbox.contains(box.x0,box.y0) and fig.bbox.contains(box.x1,box.y1),label.get_text()
    for other,b in bounds:assert not box.overlaps(b),(other,label.get_text())
    bounds.append((label.get_text(),box))
out=Path(__file__).resolve().parent
fig.savefig(out/'claim-revision.svg',facecolor='white',metadata={'Date':None});fig.savefig(out/'claim-revision.png',dpi=240,facecolor='white')
p=out/'claim-revision.svg';p.write_text('\n'.join(x.rstrip() for x in p.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8')
print('PASS: toy policy cases, English >=18pt, no clipping or overlaps.')
