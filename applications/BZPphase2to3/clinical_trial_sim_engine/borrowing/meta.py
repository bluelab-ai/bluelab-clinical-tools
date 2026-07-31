from __future__ import annotations

import math
import numpy as np
from scipy.stats import chi2


def synthesize_normal(effects: list[float], ses: list[float]):
    y=np.asarray(effects,float);v=np.asarray(ses,float)**2;w=1/v
    fixed=float(np.sum(w*y)/np.sum(w));fixed_se=float(np.sqrt(1/np.sum(w)))
    q=float(np.sum(w*(y-fixed)**2));df=max(len(y)-1,1);c=float(np.sum(w)-np.sum(w**2)/np.sum(w));tau2=max(0,(q-df)/c) if c>0 else 0
    wr=1/(v+tau2);random=float(np.sum(wr*y)/np.sum(wr));random_se=float(np.sqrt(1/np.sum(wr)))
    i2=max(0,(q-df)/q)*100 if q>0 else 0
    return {"fixed_effect":fixed,"fixed_se":fixed_se,"random_effect":random,"random_se":random_se,"q":q,"q_p":float(chi2.sf(q,df)),"i2_pct":i2,"tau2":tau2}


def dynamic_borrowing(current_effect: float,current_se: float,historical_effect: float,historical_se: float,historical_n: int,max_weight: float=.5):
    conflict_z=abs(current_effect-historical_effect)/math.sqrt(current_se**2+historical_se**2)
    compatibility=math.exp(-.5*conflict_z**2);weight=max_weight*compatibility
    current_precision=1/current_se**2;historical_precision=weight/historical_se**2
    posterior=(current_precision*current_effect+historical_precision*historical_effect)/(current_precision+historical_precision)
    posterior_se=math.sqrt(1/(current_precision+historical_precision));ess=historical_n*weight
    return {"compatibility_metric":compatibility,"conflict_z":conflict_z,"borrowing_weight":weight,"effective_historical_n":ess,"posterior_effect":posterior,"posterior_se":posterior_se,"conflict_warning":conflict_z>1.5}
