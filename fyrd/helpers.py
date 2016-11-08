# -*- coding: utf-8 -*-
"""
High level functions to make complex tasks easier.

Last modified: 2016-11-07 21:19
"""
import inspect as _inspect

###############################################################################
#                               Import Ourself                                #
###############################################################################

from . import logme as _logme
from . import options as _options
from .job import Job as _Job

###############################################################################
#                       Try Import Non-Required Modules                       #
###############################################################################

try:
    import numpy as _np
    import pandas as _pd
except ImportError:
    _logme.log('Could not import numpy and pandas for helpers', 'debug')
    pass

__all__ = ['parapply']

###############################################################################
#                                  Functions                                  #
###############################################################################


def parapply_summary(jobs, df, func, args=(), profile=None, applymap=False,
                     name='parapply', imports=None, **kwds):
    """Run parapply for a function with summary stats.

    Instead of returning the concatenated result, merge the result using
    the same function as was used during apply.

    This works best for summary functions like `.mean()`, which do a linear
    operation on a whole dataframe or series.

    Args:
        jobs (int):         Number of pieces to split the dataframe into
        df (DataFrame):     Any pandas DataFrame
        args (tuple):       Positional arguments to pass to the function,
                            keyword arguments can just be passed directly.
        profile (str):      A fyrd cluster profile to use
        applymap (bool):    Run applymap() instead of apply()
        merge_axis (int):   Which axis to merge on, 0 or 1, default is 1 as
                            apply transposes columns
        merge_apply (bool): Apply the function on the merged dataframe also
        name (str):         A prefix name for all of the jobs
        imports (list):     A list of imports in any format, e.g.
                            ['import numpy', 'scipy', 'from numpy import mean']

        Any keyword arguments recognized by fyrd will be used for job
        submission.

        *Additional keyword arguments will be passed to DataFrame.apply()*

    Returns:
        DataFrame: A recombined DataFrame
    """
    out = parapply(jobs, df, func, args, profile, applymap, name=name,
                   merge_axis=1, imports=imports, **kwds)

    # Pick function and get args
    sub_func = _run_applymap if applymap else _run_apply
    pandas_kwds = _options.split_keywords(kwds)[1]

    # Transpose
    out = out.T

    # Run the function again
    return sub_func(out, func, args, pandas_kwds)


def parapply(jobs, df, func, args=(), profile=None, applymap=False,
             merge_axis=0, merge_apply=False, name='parapply', imports=None,
             **kwds):
    """Split a dataframe, run apply in parallel, return result.

    This function will split a dataframe into however many pieces are requested
    with the jobs argument, run apply in parallel by submitting the jobs to the
    cluster, and then recombine the outputs.

    If the 'clean_files' and 'clean_outputs' arguments are not passed, we
    delete all intermediate files and output files by default.

    This function will take any keyword arguments accepted by Job, which can
    be found by running fyrd.options.option_help(). It also accepts any of
    the keywords accepted by by pandas.DataFrame.apply(), found
    `here <http://pandas.pydata.org/pandas-docs/stable/generated/pandas.DataFrame.apply.html>`_

    Args:
        jobs (int):         Number of pieces to split the dataframe into
        df (DataFrame):     Any pandas DataFrame
        args (tuple):       Positional arguments to pass to the function,
                            keyword arguments can just be passed directly.
        profile (str):      A fyrd cluster profile to use
        applymap (bool):    Run applymap() instead of apply()
        merge_axis (int):   Which axis to merge on, 0 or 1, default is 1 as
                            apply transposes columns
        merge_apply (bool): Apply the function on the merged dataframe also
        name (str):         A prefix name for all of the jobs
        imports (list):     A list of imports in any format, e.g.
                            ['import numpy', 'scipy', 'from numpy import mean']

        Any keyword arguments recognized by fyrd will be used for job
        submission.

        *Additional keyword arguments will be passed to DataFrame.apply()*

    Returns:
        DataFrame: A recombined DataFrame
    """
    # Handle arguments
    fyrd_kwds, pandas_kwds = _options.split_keywords(kwds)
    if not isinstance(jobs, int):
        raise ValueError('Jobs argument must be an integer.')

    # Set up auto-cleaning
    if 'clean_files' not in fyrd_kwds:
        fyrd_kwds['clean_files'] = True
    if 'clean_outputs' not in fyrd_kwds:
        fyrd_kwds['clean_outputs'] = True

    # Split dataframe
    dfs = _np.array_split(df, jobs)

    # Pick function
    sub_func = _run_applymap if applymap else _run_apply

    # Add all imports from the function file to globals
    rootmod = _inspect.getmodule(func)
    globals()[rootmod.__name__] = rootmod
    for k, v in _inspect.getmembers(rootmod, _inspect.ismodule):
        if not k.startswith('__'):
            globals()[k] = v

    # Some sane imports
    if imports:
        if isinstance(imports, str):
            imports = [imports]
        imports = list(iter(imports))
    else:
        imports = []
    imports += ['import numpy as np', 'import numpy', 'import scipy as sp',
                'import sp', 'import pandas as pd', 'import pandas',
                'from matplotlib import pyplot as plt',
                'from scipy import stats']

    # Run the functions
    outs = []
    count=1
    for d in dfs:
        nm = '{}_{}_of_{}'.format(name, count, jobs)
        outs.append(
            _Job(sub_func, (d, func, args, pandas_kwds),
                 profile=profile, name=nm, imports=imports,
                 **fyrd_kwds).submit()
        )
        count += 1

    # Get the results
    results = []
    for out in outs:
        try:
            results.append(out.get())
        except IOError:
            _logme.log('Result getting failed, most likely one of the child ' +
                       'jobs crashed, check the error files', 'critical')
            raise

    # Return the recombined DataFrame
    try:
        out = _pd.concat(results, axis=merge_axis)
    except ValueError:
        _logme.log('DataFrame concatenation failed!', 'critical')
        raise

    if merge_apply:
        out = sub_func(out, func, args, pandas_kwds)

    return out


def _run_apply(df, func, args=None, pandas_kwds=None):
    """Run DataFrame.apply().

    Args:
        df (DataFrame):     Any pandas DataFrame
        args (tuple):       A tuple of arguments to submit to the function
        pandas_kwds (dict): A dictionary of keyword arguments to pass to
                            DataFrame.apply()

    Returns:
        DataFrame: The result of apply()
    """
    apply_kwds = {'args': args} if args else {}
    if pandas_kwds:
        apply_kwds.update(pandas_kwds)
    return df.apply(func, **apply_kwds)


def _run_applymap(df, func, args=None, pandas_kwds=None):
    """Run DataFrame.applymap().

    Args:
        df (DataFrame):     Any pandas DataFrame
        args (tuple):       A tuple of arguments to submit to the function
        pandas_kwds (dict): A dictionary of keyword arguments to pass to
                            DataFrame.apply()

    Returns:
        DataFrame: The result of apply()
    """
    apply_kwds = {'args': args} if args else {}
    if pandas_kwds:
        apply_kwds.update(pandas_kwds)
    return df.applymap(func, **apply_kwds)
