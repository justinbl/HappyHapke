from __future__ import division, print_function
import numpy as np
import scipy.io
from matplotlib import pyplot as plt
#Fix for Error in Section 3 - Solve For K in external Library Matplotlib
plt.switch_backend('agg')
from scipy.optimize import least_squares
from scipy.integrate import trapz
from scipy.interpolate import PchipInterpolator
from scipy import interpolate
from scipy import arange, array, exp
import math

def loadmat_single(path_or_file_obj):
  """Loads one array from a MAT-file or ascii file."""
  try:
    return np.loadtxt(path_or_file_obj)
  except ValueError:
    # must be a .mat file, so rewind to try again
    if hasattr(path_or_file_obj, 'seek'):
      path_or_file_obj.seek(0)
  mat = scipy.io.loadmat(path_or_file_obj, appendmat=False)
  keys = [k for k in mat.keys() if not k.startswith('_')]
  if len(keys) != 1:
    raise ValueError('loadmat_single expects one variable, got %r' % keys)
  return mat[keys[0]]


def prepare_spectrum(wavelength, spec, low, high):
  # make sure wavelength is in microns
  if wavelength[0] > 100:
      wavelength /= 1000

  # extract usable data
  idx1, idx2 = np.searchsorted(wavelength, (low, high))
  return wavelength[idx1:idx2], spec[idx1:idx2]


def fit_left_side(wavelength, spec, UV, fit_order=0):
  # fit the left end of the data with a polynomial
  lamdiff = wavelength[1] - wavelength[0]
  leftw = np.arange(UV, wavelength[0], lamdiff)
  if fit_order == 0:
    # extrapolate left side of k to 0.2 using ahrekiel's constant method
    # Cloutis 2008b shows that jarosite is essentially flat from 200-400nm
    padding = np.zeros_like(leftw)
    spec = np.concatenate((padding + spec[0], spec))
  else:
    # define end of curve to fit
    idx = len(leftw) + 1 # Change 1 to optional user input
    fit_order = min(fit_order, len(leftw))
    # fit curves
    # Takes the wavelength, spectrum points as x,y and fits a polynomial on it. Degree is the fitorder variable 
    # poly1d makes a one-d polynomial from the co-efficients returned by the polyfit method 
    poly = np.poly1d(np.polyfit(wavelength[:idx], spec[:idx], fit_order))
    spec = np.concatenate((poly(leftw), spec))
  wavelength = np.concatenate((leftw, wavelength))
  return np.column_stack((wavelength, spec))


def preprocess_traj(traj, low, high, UV, fit_order=0):
  wave, spec = traj.T
  wave, spec = prepare_spectrum(wave, spec, low, high)
  return fit_left_side(wave, spec, UV, fit_order=fit_order)

#Solving for K - Logic -- setup the matrices here. For plotting get values from the hapke object - defined in hapke_model.py
def MasterHapke1_PP(hapke, traj, b, c, ff, s, D, debug_plots=False):
  wavelength, reflect = traj.T
  table_size = len(traj) * 2

  # make sure we have a scalar isow
  if hapke.needs_isow:
    assert np.isscalar(hapke.isow), 'MasterHapke1_PP requires scalar isow'

  # create table of increasing w (single scattering albedo) and use linear
  # interpolation to solve backwards from the real reflectance data
  w = np.linspace(0, 1, table_size, endpoint=False)
  rc = hapke.radiance_coeff(w, b, c, ff)
  w2 = np.interp(reflect, rc, w)

  # use the same trick to back-solve for k from w2, except we have to plug in
  # the (k/wavelength) term when interpolating
  # TODO: incorporate bounds on k to determine table bounds
  k_wave = np.logspace(-1, -7, table_size)
  scat = hapke.scattering_efficiency(k_wave, 1, D, s)
  k_wave2 = np.interp(w2, scat, k_wave)
  k = k_wave2 * wavelength

  if debug_plots:
    # calculate scattering efficiency for each solved k
    rc2 = hapke.radiance_coeff(w2, b, c, ff)
    ScatAlb = hapke.scattering_efficiency(k, wavelength, D, s)
    rc3 = hapke.radiance_coeff(ScatAlb, b, c, ff)

    #The _ is the figure and the axes object is stores in axes
    _, axes = plt.subplots(figsize=(10,4), nrows=2, ncols=2, sharex=True)
    # plot reflectance data and rc2 for comparison
    ax = axes[0,0] #Position of the plots
    ax.plot(wavelength, reflect)
    ax.plot(wavelength, rc2, '--')# Third argument is for dotted lines
    ax.set_ylabel('Reflectance (#)')
    ax.set_title('Fit #1: scattering')
    ax2 = ax.twinx() # Makes another invisible copy of the X Axis -- that is shared from the previous plot
    ax2.plot(wavelength, np.abs(rc2 - reflect), 'k-', lw=1, alpha=0.75) #arguements are x data, y data, black solid line, line width and opacity
    ax2.set_ylabel('Fit Error')
    ax2.ticklabel_format(axis='y', style='sci', scilimits=(-3,3))

    # plot w2 and single scattering albedo
    ax = axes[0,1]
    ax.plot(wavelength, w2)
    ax.plot(wavelength, ScatAlb, '--')
    ax.set_title('Fit #2: k')
    ax.set_ylabel('Scattering Albedo')
    ax2 = ax.twinx()
    ax2.plot(wavelength, np.abs(w2 - ScatAlb), 'k-', lw=1, alpha=0.75)
    ax2.set_ylabel('Fit Error')
    ax2.ticklabel_format(axis='y', style='sci', scilimits=(-3,3))

    # plot reflectance vs rc3
    ax = axes[1,0]
    ax.plot(wavelength, reflect)
    ax.plot(wavelength, rc3, '--')
    ax.set_ylabel('Reflectance (#)')
    ax.set_xlabel('Wavelength (um)')
    ax.set_title('Combined fit')
    ax2 = ax.twinx()
    ax2.plot(wavelength, np.abs(rc3 - reflect), 'k-', lw=1, alpha=0.75)
    ax2.set_ylabel('Fit Error')
    ax2.ticklabel_format(axis='y', style='sci', scilimits=(-3,3))

    # plot fitted k
    ax = axes[1,1]
    ax.semilogy(wavelength, k) #Plot the graph in Log Scaling
    ax.set_ylabel('fitted k')
    ax.set_xlabel('Wavelength (um)')

    #A list for all the data that is plotted
    scat_eff_for_k = [ 
                        ['Wavelength Vs Reflect',wavelength, reflect],
                        ['Wavelength Vs Rc2', wavelength, rc2],
                        ['Wavelength Vs Rc2-Reflect', wavelength, np.abs(rc2 - reflect)],
                        ['Wavelength Vs W2', wavelength, w2], 
                        ['Wavelength Vs Scat Alb', wavelength, ScatAlb],
                        ['Wavelength Vs W2-ScatAlb', wavelength, np.abs(w2 - ScatAlb)],
                        ['Wavelength Vs Rc3', wavelength, rc3],
                        ['Wavelength Vs Rc3-Reflect', wavelength, np.abs(rc3 - reflect)],
                        ['Wavelength Vs K', wavelength, k]
                     ]
  return k, scat_eff_for_k

#Find what is magic 12
def MasterHapke2_PP(hapke, spectra, coefg, lb, ub, ff, spts=1, **kwargs):
  """This program performs an iterative minimization using Hapke's radiative
  transfer theory to find a global and grain-size independent value of
  imaginary index of refraction, k."""
  no_of_grain_samples = len(spectra)
  total_guesses = no_of_grain_samples * 4 # 4 values (b,c,s,D) for each grain size

  wave = spectra['file2'][:,0]
  actuals = [spectra[key][:,1] for key in sorted(spectra.keys())]

  #Why 3 
  def obj_fn(coef):
    k = coef[total_guesses:]
    loss = 0
    for i, actual in enumerate(actuals):
      b, c, s, D = coef[i:total_guesses:no_of_grain_samples]
       #these are paired correctly now that it is sorted elsewheres
      scat = hapke.scattering_efficiency(k, wave, D, s)
      rc = hapke.radiance_coeff(scat, b, c, ff[i])
      loss += ((rc - actual)**2).sum()
    return np.sqrt(loss)

  start_points = np.empty((spts, len(coefg)))
  start_points[0] = coefg

  #Initialize random start points
  for i in range(1, spts):
    start_points[i] = np.random.uniform(lb, ub)

  #Start Points is 215 + 4 * no of grain samples

  bounds = np.row_stack((lb, ub))

  solutions = []
  #For each start point - minimize the least square error and append it to solutions.
  for spt in start_points:
    res = least_squares(obj_fn, spt, bounds=bounds, ftol=1.0e-16, xtol=2.23e-16,x_scale = 'jac', method='trf', max_nfev=1, **kwargs)
    #res = least_squares(obj_fn, spt, bounds=bounds, method='trf', **kwargs)
    solutions.append(res)
  return solutions

##Used in Section Addd MIR Data
def MasterKcombine(mir_k, mir_v, wavelength, global_k, adjType):

    if adjType == '4':
        return no_mir_data(wavelength, global_k)

    k = loadmat_single(mir_k).ravel()
    v = loadmat_single(mir_v).ravel()
    
    #as iof MaskerKcombine_Bas.mat -- we need to plot the k and v
    _, axes = plt.subplots(figsize=(12,6), nrows=2, ncols=2)
    ax1 = axes[0,0]
    ax1.plot(v,k)
    ax1.set_ylabel('k')
    ax1.set_xlabel('Wavenumber (cm-1)')
    ax1.set_title('MIR k')
    ax1.invert_xaxis()

    #If you are changing anything here please change in no_mir_data()
    lam = wavelength
    vnirk = global_k

    #Plot vnirk vs wavelength -- 
    #If you are changing anything here please change in no_mir_data() where the same is plotted
    ax2 = axes[0,1]
    ax2.plot(lam, vnirk)
    ax2.set_ylabel('k')
    ax2.set_xlabel('Wavelength(um)')
    ax2.set_title('VNIR k')

    # a little modeling magic to make the arrays meet
    # in case you cut off some noise at the end

    # get a frequency space vector for vnirk
    #If you are changing anything here please change in no_mir_data()
    vnirv = 10000 / lam

    #Reverse only if not in ascending
    if vnirv[-1] < vnirv[0]:
        rev_vnirv = np.flip(vnirv, axis=0)
        rev_vnirk = np.flip(vnirk, axis=0)

    #If you are changing anything here please change in no_mir_data() where the same is plotted
    ax3 = axes[1,0]
    ax3.semilogy(vnirv, vnirk)
    ax3.set_ylabel('k')
    ax3.set_xlabel('Wavenumber(cm e-1)')
    ax3.set_title('Wavenumber(cm e-1) vs K')
    ax3.invert_xaxis() 

    #Evenly Spacing stuff
    vdiff = abs(v[1] - v[0])

    #Determine # of pts in VNIRV
    vnirvsize = round(abs(rev_vnirv[0] - rev_vnirv[-1])) / vdiff
    vnirvdiff =(abs(vnirv[0]-vnirv[-1]))/vnirvsize; 
    even_vnirv = np.linspace(rev_vnirv[0], rev_vnirv[-1], vnirvsize)
    interp_ob = PchipInterpolator(rev_vnirv, rev_vnirk)
    even_vnirk = interp_ob(even_vnirv)
    #This now has the same point spacing as v, so we should have same weight in integral

    #Taking out the noise
    noisy_end = max(lam)
    vals = abs(even_vnirv - 10000/noisy_end)
    minloc = np.argmin(vals) + 1 # Remove the noisy end
    new_vnirv = even_vnirv[minloc:] #even vnirv - is in ascending order -- so we need to get from minloc
    new_vnirk = even_vnirk[minloc:]

    ax4 = axes[1,1]
    ax4.semilogy(vnirv, vnirk, label='VNIR k')
    ax4.semilogy(even_vnirv, even_vnirk, '--r', label='Evenly spaced VNIR k')
    ax4.semilogy(new_vnirv, new_vnirk, '-.g', label = 'VNIR k without noisy end')
    ax4.legend()
    ax4.set_ylabel('k')
    ax4.set_xlabel('Wavenumber(cm e-1)')
    ax4.set_title('VNIR k')
    ax4.invert_xaxis()

    #Make sure we are combining this correctly
    #We want to be in descending wavenumbers
    #Find the low end of vnirv (high wavelength)
    if new_vnirv[0] > new_vnirv[-1]:
        vnirv_end = new_vnirv[-1]
    else:
        new_vnirv = np.flip(new_vnirv, axis=0)
        new_vnirk = np.flip(new_vnirk, axis=0)
        vnirv_end = new_vnirv[-1]

    #Find High end of v 
    if v[0] > v[-1]:
        v_end = v[-1]
    else:
        v = np.flip(v, axis=0)
        k = np.flip(k, axis=0)
        v_end = v[0] # Note that v[-1] and v_end will not be the same

    plt_data = [
                ['MIR k', v, k],
                ['VNIR k', lam, vnirk],
                ['Wavenumber(cm e-1) vs K', vnirv, vnirk],
                ['Evenly Spaced VNIR k', even_vnirv, even_vnirk],
                ['VNIR k without noisy end', new_vnirv, new_vnirk]
               ]

    cache = (v, k, lam, vnirk, vnirv, rev_vnirk, rev_vnirv, even_vnirk, even_vnirv, new_vnirk, new_vnirv, vnirv_end, v_end, vdiff, vnirvdiff)

    if adjType == '0':
        pltdata2, kset = adj_method_0(cache)
    elif adjType == '1':
        pltdata2, kset = adj_method_1(cache)
    elif adjType == '2':
        pltdata2, kset = adj_method_2(cache)
    elif adjType == '3':
        pltdata2, kset = adj_method_3(cache)

    plt_data.extend(pltdata2)

    return plt_data, kset

def adj_method_0(cache):
    plt_data = []
    (v, k, lam, vnirk, vnirv, rev_vnirk, rev_vnirv, even_vnirk, even_vnirv, new_vnirk, new_vnirv, vnirv_end, v_end, vdiff, vnirvdiff) = cache

    if v_end < vnirv_end:
        vcon = np.linspace(vnirv_end-vdiff, v_end+vdiff, round(abs((v_end+vdiff)-(vnirv_end-vdiff))/vdiff));
        m = (k[0]-new_vnirk[-1])/(v[0]-new_vnirv[-1]);
        #remember that they are arranged by decreasing wavenumber
        kcon = np.zeros(vcon.shape);
        for i in range(len(vcon)):
            kcon[i] = m*(vcon[i]-new_vnirv[-1])+new_vnirk[-1]
        fullv = np.concatenate((new_vnirv, vcon, v), axis=None)
        fullk = np.concatenate((new_vnirk, kcon, k), axis=None)

        fig1, ax1 = plt.subplots(figsize=(6, 4), frameon=False)
        ax1.semilogy(v, k, label='MIR k')
        ax1.semilogy(new_vnirv, new_vnirk, label='Evenly spaced VNIR k')
        ax1.semilogy(vcon, kcon,  label = 'Extended k')
        ax1.semilogy(fullv, fullk, label = 'Whole k')
        ax1.legend()
        ax1.set_xlabel('Wavenumber(cm e-1)')
        ax1.set_ylabel('k')
        ax1.set_title('Combined k')
        ax1.invert_xaxis()
        plt_data.extend([['Extended K', vcon, kcon],['Whole k', fullv, fullk]])

        nv = v
        nk = k
    elif v_end >= vnirv_end:
        #cut some off MIR to connect the dots
        min_index = np.argmin(abs(v-vnirv_end))
        v_end = v[min_index]
        nv = v[min_index+1:]
        nk = k[min_index+1:]
        #remember that they are arranged by decreasing wavenumber
        fullv = np.concatenate((new_vnirv,nv), axis=None)
        fullk = np.concatenate((new_vnirk,nk), axis=None)
        
        fig1, ax1 = plt.subplots(figsize=(6, 4), frameon=False)
        ax1.semilogy(v, k, label='MIR k')
        ax1.semilogy(nv, nk, label='Cropped MIR k')
        ax1.semilogy(new_vnirv, new_vnirk, label = 'Evenly spaced VNIR k')
        ax1.semilogy(fullv, fullk, label = 'Whole k')
        ax1.legend()
        ax1.set_xlabel('Wavenumber(cm e-1)')
        ax1.set_ylabel('k')
        ax1.set_title('Combined k')
        ax1.invert_xaxis()
        
        plt_data.extend([['Cropped MIR K', nv, nk],['Whole k', fullv, fullk]])

    kset = (vnirv, vnirk, fullv, fullk)

    return plt_data, kset

def adj_method_1(cache):
    plt_data = []
    (v, k, lam, vnirk, vnirv, rev_vnirk, rev_vnirv, even_vnirk, even_vnirv, new_vnirk, new_vnirv, vnirv_end, v_end, vdiff, vnirvdiff) = cache

    #Make a linearly increasing array
    y = np.linspace(0.0000001, 1, len(k))
    #Make an array that is exponential in logspace
    y_scale = 10**(y**10)
    #Flip it so that it is multiplying correctly
    y_scale = np.flip(y_scale, axis=0)
    #Adjust MIR k by dividing the scaling factor
    nk = k / y_scale

    #Plot
    fig1, ax1 = plt.subplots(figsize=(6, 4), frameon=False)
    ax1.semilogy(v, k, label='MIR k')
    ax1.semilogy(v, nk, label='Scaled MIR k')
    ax1.semilogy(even_vnirv, even_vnirk,  label = 'Evenly spaced VNIR k')
    ax1.legend()
    ax1.set_xlabel('Wavenumber(cm e-1)')
    ax1.set_ylabel('k')
    ax1.set_title('VNIR k')
    ax1.invert_xaxis()
    plt_data.append(['Evenly Spaced MIR K', v, nk])

    #Now quick and dirty linear connection
    if v_end < vnirv_end:
        vcon = np.linspace(vnirv_end - vdiff, vnirv_end + vdiff, round(abs((v_end + vdiff) - (vnirv_end - vdiff)) / vdiff))
        m = (nk[0] - new_vnirk[-1]) / ( v[0] - new_vnirv[-1])
        # Remember that they are arranged by decreasing wavenumber
        kcon = np.zeros(vcon.shape)
        for i in range(len(vcon)):
            kcon[i] = m * ( vcon[i] - new_new_vnirv[-1]) + new_vnirk[-1]
        full_v = np.concatenate((new_vnirv, vcon, v), axis=None) # Default axis = 0. Row-wise
        full_k = np.concatenate((new_vnirk, kcon, nk), axis=None)

        fig2, ax2 = plt.subplots(figsize=(6, 4), frameon=False)
        ax2.semilogy(v, k, label='MIR k')
        ax2.semilogy(v, nk, label='Scaled MIR k')
        ax2.semilogy(new_vnirv, new_vnirk, label = 'Evenly spaced VNIR k')
        ax2.semilogy(vcon, kcon, label = 'Extended k')
        ax2.semilogy(full_v, full_k, label = 'Whole k')
        ax2.legend()
        ax2.set_xlabel('Wavenumber(cm e-1)')
        ax2.set_ylabel('k')
        ax2.set_title('VNIR k')
        ax2.invert_xaxis()
        plt_data.extend([['Scaled MIR K', v, nk],['Whole k', fullv, fullk], ['Extended k', vcon, kcon]])

    elif v_end >= vnirv_end:
        #Cut some off MIR to connect the dots
        min_index = np.argmin(abs(v - vnirv_end))
        v_end = v[min_index]
        nv = v[(min_index + 1):]
        nk = nk[(min_index+1):]

        #Remember that they are arranged by decreasing wavenum
        fullv = np.concatenate((new_vnirv, nv), axis=None) # Default axis = 0. Row-wise
        fullk = np.concatenate((new_vnirk, nk), axis=None)

        fig2, ax2 = plt.subplots(figsize=(6, 4), frameon=False)
        ax2.semilogy(v, k, label='MIR k')
        ax2.semilogy(nv, nk, label='scaled MIR k')
        ax2.semilogy(new_vnirv, new_vnirk, label = 'Evenly spaced VNIR k')
        ax2.semilogy(fullv, fullk, label = 'Whole k') ## There is a additional label in the matlab code
        ax2.legend()
        ax2.set_xlabel('Wavenumber(cm e-1)')
        ax2.set_ylabel('k')
        ax2.set_title('Combined k')
        ax2.invert_xaxis()
        plt_data.extend([['Scaled MIR K', nv, nk],['Whole k', fullv, fullk]])
    
    kset = (vnirv, vnirk, fullv, fullk)

    return plt_data, kset

def adj_method_2(cache):
    plt_data = []
    (v, k, lam, vnirk, vnirv, rev_vnirk, rev_vnirv, even_vnirk, even_vnirv, new_vnirk, new_vnirv, vnirv_end, v_end, vdiff, vnirvdiff) = cache
    if v_end < vnirv_end:
        new_end = v_end # - vnirvdiff -- taking this out leads to a double point later
        #Fit the end of the data so that it will meet the MIR data
        ## Requires different functions sometimes, try POLY3, POLY4
        # deifine end of curve to fit
        #cut off any noise at end commented out 7/17/18 FEEL FREE TO CHANGE
        #lam=lam(1:noisend);
        #vnirk=vnirk(1:noisend);
        #set area to fit with a curve FEEL FREE TO CHANGE
        ep = len(new_vnirv)
        sp = ep - 30
        short_vnirv = new_vnirv[sp:ep]
        short_vnirk = new_vnirk[sp:ep]

        #Fit Curve
        fcoef = np.polyfit(short_vnirv, short_vnirk, 1)

        #extrapolate the end of lam
        #find spacing
        vspace = round(abs(new_vnirv[-1] - new_end) / vnirvdiff)
        vnirvext = np.linspace(new_vnirv[-1], new_end, vspace)
        #evaluate the function over the new range
        extrak=evalPoly(fcoef, vnirvext)

        #plot it to see how we did
        fig1, ax1 = plt.subplots(figsize=(6, 4), frameon=False)
        ax1.semilogy(vnirv, vnirk, label='VNIR k')
        ax1.semilogy(new_vnirv, new_vnirk,  label='Shortened VNIR k')
        ax1.semilogy(even_vnirv, even_vnirk,label = 'Evenly spaced VNIR k')
        ax1.semilogy(vnirvext, extrak, label = 'Extended k')
        ax1.legend()
        ax1.set_xlabel('Wavenumber(cm e-1)')
        ax1.set_ylabel('k')
        ax1.set_title('Extended VNIR k')
        ax1.invert_xaxis()
        plt_data.append(['Extended k', vnirvext, extrak])
        
        #combine fit end with data (for this step only)
        fvnirk=np.concatenate((new_vnirk,extrak), axis=None)
        fv=np.concatenate((new_vnirv,vnirv_end), axis=None)
    else:
        fvnirk=new_vnirk # oveflap dealt with in next section for this method
        fv=new_vnirv; 

    #HERE IS WHERE WE ADJUST THE MIR DATA DOWN TO THE VNIR DATA (n would go up
    #based on epsilon infinity values so k goes down)
    #deal with potential overlap
    if max(v) > min(fv):
        minloc = np.argmin(abs(v-min(fv)))
        nv=v[minloc+1:]
        nk=k[minloc+1:]
    else:#no overlap
        nv=v
        nk=k

    #remember we know we are in descending frequency space
    #find difference between the two k values
    offset=nk[0]-fvnirk[-1]
    #DEALING WITH THE POSSIBILITY THAT LOWERING MIRK MAKES NEG
    #print error message
    if min(nk-offset) <= 0:
        raise ValueError('MIR k will be negative, choose another adj_method')
    elif min(nk-offset) > 0:
        adjk = nk-offset
        
        #plot it to make sure it worked
        fig2, ax2 = plt.subplots(figsize=(6, 4), frameon=False)
        ax2.semilogy(v, k, label='MIR k')
        ax2.semilogy(nv, adjk, label='Adjusted MIR k')
        ax2.legend()
        ax2.set_xlabel('Wavenumber(cm e-1)')
        ax2.set_ylabel('k')
        ax2.set_title('MIR k Adjustment')
        ax2.invert_xaxis()
        plt_data.append(['Adjusted MIR k', nv, adjk])

        fullv = np.concatenate((nv,fv), axis=None)
        fullk = np.concatenate((adjk,fvnirk), axis=None)
    
        fig3, ax3 = plt.subplots(figsize=(6, 4), frameon=False)
        ax3.semilogy(fullv, fullk, label='Combined k')
        ax3.semilogy(nv, adjk, label='Adjusted MIR k')
        ax3.semilogy(fv, fvnirk, label='VNIR k')
        ax3.legend()
        ax3.set_xlabel('Wavenumber(cm e-1)')
        ax3.set_ylabel('k')
        ax3.set_title('Combined k')
        ax3.invert_xaxis()
        plt_data.extend([['Combined k', fullv, fullk], ['VNIR k', fv, fvnirk]])
    
    kset = (vnirv, vnirk, fullv, fullk)

    return plt_data, kset

def adj_method_3(cache): #this will bring MIRk down some VNIRk up some and draw line
    plt_data = []
    (v, k, lam, vnirk, vnirv, rev_vnirk, rev_vnirv, even_vnirk, even_vnirv, new_vnirk, new_vnirv, vnirv_end, v_end, vdiff, vnirvdiff) = cache

    if v_end < vnirv_end:
        high = min(k)
        low = max(new_vnirk)
        offset = high - low
        adjk = k - offset
        vcon = np.linspace(vnirv_end-vdiff,v_end+vdiff, round(abs((v_end+vdiff)-(vnirv_end-vdiff))/vdiff))
        m = (adjk[0]-new_vnirk[-1])/(v[0]-new_vnirv[-1])
        #remember that they are arranged by decreasing wavenumber
        kcon = np.zeros(vcon.shape)
        for i in range(len(vcon)):
            kcon[i] = m*(vcon[i]-new_vnirv[-1])+new_vnirk[-1]

        fullv = np.concatenate((new_vnirv,vcon,v), axis=None)
        fullk = np.concatenate((new_vnirk,kcon,adjk), axis=None)

        fig1, ax1 = plt.subplots(figsize=(6, 4), frameon=False)
        ax1.semilogy(v, k, label='MIR k')
        ax1.semilogy(v, adjk, label='Adjusted MIR k')
        ax1.semilogy(new_vnirv, new_vnirk, label='Evenly Spaced VNIR k')        
        ax1.semilogy(vcon, kcon, label='Extended k')        
        ax1.semilogy(fullv, fullk, label='Whole k')
        ax1.legend()
        ax1.set_xlabel('Wavenumber(cm e-1)')
        ax1.set_ylabel('k')
        ax1.set_title('Combined k')
        ax1.invert_xaxis()
        plt_data.extend([['Adjusted MIR K', v, adjk],['Whole k', fullv, fullk], ['Extended k', vcon, kcon]])

        nv = v
        nk = k
    elif v_end >= vnirv_end:
        high = min(k)
        low = max(new_vnirk)
        offset = high-low
        adjk = k - offset
        #cut some off MIR to connect the dots
        min_index = np.argmin(abs(v-vnirv_end))
        v_end = v[min_index]
        nv = v[min_index+1:]
        nk = k[min_index+1:]
        #remember that they are arranged by decreasing wavenumber
        fullv = np.concatenate((new_vnirv,nv), axis=None)
        fullk = np.concatenate((new_vnirk,nk), axis=None)
        
        fig1, ax1 = plt.subplots(figsize=(6, 4), frameon=False)
        ax1.semilogy(v, k, label='MIR k')
        ax1.semilogy(v, adjk, label='Adjusted MIR k')        
        ax1.semilogy(nv, nk, label='Cropped MIR k')    
        ax1.semilogy(new_vnirv, new_vnirk, label='Evenly Spaced VNIR k')
        ax1.semilogy(fullv, fullk, label='Whole k')
        ax1.legend()
        ax1.set_xlabel('Wavenumber(cm e-1)')
        ax1.set_ylabel('k')
        ax1.set_title('Combined k')
        ax1.invert_xaxis()
        plt_data.extend([['Adjusted MIR K', v, adjk],['Whole k', fullv, fullk], ['Cropped MIR k', nv, nk]])
        
    kset = (vnirv, vnirk, fullv, fullk)

    return plt_data, kset

def evalPoly(lst, x):
    total = []
    for power, coeff in enumerate(lst):
        total.append((x**power) * coeff)
    return sum(total)

def no_mir_data(lam, vnirk):
    vnirv = 10000 / lam
    fig, axes = plt.subplots(figsize=(12,3), nrows=1, ncols=2)
    
    #Plot vnirk vs wavelength
    #If you are changing anything here please change in MaskerKCombine() where the same is plotted    
    ax1 = axes[0]
    ax1.plot(lam, vnirk)
    ax1.set_ylabel('k')
    ax1.set_xlabel('Wavelength(um)')
    ax1.set_title('VNIR k')
    
    # get a frequency space vector for vnirk
    vnirv = 10000 / lam

    #If you are changing anything here please change in MaskerKCombine() where the same is plotted  
    ax2 = axes[1]
    ax2.semilogy(vnirv, vnirk)
    ax2.set_ylabel('k')
    ax2.set_xlabel('Wavenumber(cm e-1)')
    ax2.set_title('Wavenumber(cm e-1) vs K')
    ax2.invert_xaxis() 

    plt_data = [
                ['VNIR k', lam, vnirk],
                ['Wavenumber(cm e-1) vs K', vnirv, vnirk]
               ]

    kset = vnirv, vnirk, None, None
    
    return plt_data, kset

def MasterSSKK(kset, anchor, iter, wavelength, n1, lstart, lend):
    #I am using the VNIRV from the previous step - unlike the MATLAB code - Check with ELI
    vnirv, vnirk, fullv, fullk = kset
    lam = wavelength
    
    #get info on first and last element to re interpolate
    first = vnirv[0]
    last = vnirv[-1]
    sizev = len(vnirv)

    ## Skip -- kcombine option added 
    if fullv is None and fullk is None:

        #Check if vnirv, vnirk is in ascending
        if vnirv[-1] < vnirv[0]:
            vnirv = np.flip(vnirv, axis=0)
            vnirk = np.flip(vnirk, axis=0)

        fullv = np.linspace(first, last, sizev)
        interp_ob = interpolate.interp1d(vnirv, vnirk, kind='linear')
        fullk = interp_ob(fullv)

    kap = fullk
    v = fullv


    #Check if fullv, fullk is in ascending
    if v[-1] < v[0]:
        v = np.flip(v, axis=0)
        kap = np.flip(kap, axis=0)

    #Size of data set
    sizev = len(v)

    #define the real index of refraction and the anchor point
    lam1 = float(anchor) #average of sodium D doublet
    v1 = 10000/lam1 #converted to frequency

    # intnb : specifies the number of intervals to run approximation over
    # (originally 1000, but that seemed excessive)
    intnb=10

    #make start point and end point values for integration that place k at the
    #center of each range
    dv = v[1] - v[0]
    dx = dv / intnb #spacing for all x's
    halfv = dv/2;
    offset = np.linspace(-halfv, halfv, intnb) #10 evenly spaced steps in every dv
    xx = np.matlib.repmat(v, intnb, 1) + np.matlib.repmat(offset, sizev, 1).T
    #xx is ten rows to comput simultaneously, 1 for each offset for each v

    # compute all the bits that don't change in the loop.
    v_sq = v**2
    v1_sq = v1**2
    n = (2/math.pi)*(v_sq-v1_sq)*dx #rename. n is confusing
    xx_sq = xx**2 #v'^2
    tmp = xx_sq - v1_sq #v'^2-v1^2
    numerator = xx * np.matlib.repmat(kap, intnb, 1) #v'*k(v')

    for j in range(len(v)):
        # progress counter
        if j % 100 == 0:
            print('Iteration '+str(j)+' of '+str(len(v)))
        #Compute function over all xx for each v_j
        yy = numerator /((xx_sq-v_sq[j]) * tmp)
        # calculate the real index of refraction with integral over intnb grid
        n[j] = n[j] * np.sum(np.trapz(yy))
    n += n1

    #extract VNIR n and save to different file for later
    vlam = 10000 /v 
    nlam = n

    #make sure in same order as k will be
    if vlam[0] > vlam[-1]:
        vlam = np.flip(vlam, axis=0)
        nlam = np.flip(n, axis=0)
 
    lamdiff = lam[1] - lam[0]
    # lstart comes from UV

    #get actual k wavelength becuase stupid floating points are not working
    ### what is wavelength
    ksize=int(len(wavelength))
    vislam=wavelength[:ksize]

    #lstart=lstart+iter*lamdiff;
    dist = abs(vlam - lend)
    minloc = np.argmin(dist)
    upend = minloc
    dist = abs(vlam - lstart)
    minloc = np.argmin(dist)
    downend = minloc

    ## Python finds a different minimum than MATLAB does by one point less in the array in Python

    visvlam = vlam[downend:upend]
    vnirn = nlam[downend:upend]
    #extrapolate to k spacing
    interp_ob  = interpolate.interp1d(visvlam,  vnirn, fill_value='extrapolate') ## Need to check if this extrapolates
    visn = interp_ob(vislam)
    
    fig1, ax1 = plt.subplots(figsize=(6, 4), frameon=False)
    ax1.plot(visvlam, vnirn, label = 'n')
    ax1.plot(vislam, visn, label = 'reinterpolated n')
    ax1.legend()
    ax1.set_xlabel('Wavelength(um)')
    ax1.set_ylabel('n')
    ax1.set_title('VNIR n')
    
    ## Note: We removed lines that save the lstart and lend -- 
    ## which are the end points that may or may not have been removed

    plt_data = [
                ['n', visvlam, vnirn],
                ['Reinterpolated n', vislam, visn]
               ]

    return plt_data