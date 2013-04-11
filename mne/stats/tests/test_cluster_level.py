import numpy as np
from numpy.testing import assert_equal, assert_array_equal,\
                          assert_array_almost_equal
from nose.tools import assert_true, assert_raises
from scipy import sparse, linalg, stats
from functools import partial

from mne.stats.cluster_level import permutation_cluster_test, \
                                    permutation_cluster_1samp_test, \
                                    spatio_temporal_cluster_test, \
                                    spatio_temporal_cluster_1samp_test, \
                                    ttest_1samp_no_p

noise_level = 20

normfactor = np.hanning(20).sum()

rng = np.random.RandomState(42)
condition1_1d = rng.randn(40, 350) * noise_level
for c in condition1_1d:
    c[:] = np.convolve(c, np.hanning(20), mode="same") / normfactor

condition2_1d = rng.randn(33, 350) * noise_level
for c in condition2_1d:
    c[:] = np.convolve(c, np.hanning(20), mode="same") / normfactor

pseudoekp = 5 * np.hanning(150)[None, :]
condition1_1d[:, 100:250] += pseudoekp
condition2_1d[:, 100:250] -= pseudoekp

condition1_2d = condition1_1d[:, :, np.newaxis]
condition2_2d = condition2_1d[:, :, np.newaxis]


def test_cluster_permutation_test():
    """Test cluster level permutations tests."""
    for condition1, condition2 in zip((condition1_1d, condition1_2d),
                                      (condition2_1d, condition2_2d)):
        T_obs, clusters, cluster_p_values, hist = permutation_cluster_test(
                                    [condition1, condition2],
                                    n_permutations=100, tail=1, seed=1)
        assert_equal(np.sum(cluster_p_values < 0.05), 1)

        T_obs, clusters, cluster_p_values, hist = permutation_cluster_test(
                                    [condition1, condition2],
                                    n_permutations=100, tail=0, seed=1)
        assert_equal(np.sum(cluster_p_values < 0.05), 1)

        # test with 2 jobs
        T_obs, clusters, cluster_p_values_buff, hist =\
            permutation_cluster_test([condition1, condition2],
                                    n_permutations=100, tail=0, seed=1,
                                    n_jobs=2)
        assert_array_equal(cluster_p_values, cluster_p_values_buff)


def test_cluster_permutation_t_test():
    """Test cluster level permutations T-test."""
    for condition1 in (condition1_1d, condition1_2d):
        # these are so significant we can get away with fewer perms
        T_obs, clusters, cluster_p_values, hist =\
            permutation_cluster_1samp_test(condition1, n_permutations=100,
                                           tail=0, seed=1)
        assert_equal(np.sum(cluster_p_values < 0.05), 1)

        T_obs_pos, c_1, cluster_p_values_pos, _ =\
            permutation_cluster_1samp_test(condition1, n_permutations=100,
                                    tail=1, threshold=1.67, seed=1)

        T_obs_neg, _, cluster_p_values_neg, _ =\
            permutation_cluster_1samp_test(-condition1, n_permutations=100,
                                    tail=-1, threshold=-1.67, seed=1)
        assert_array_equal(T_obs_pos, -T_obs_neg)
        assert_array_equal(cluster_p_values_pos < 0.05,
                           cluster_p_values_neg < 0.05)

        # test with 2 jobs
        T_obs_neg, _, cluster_p_values_neg_buff, _ = \
            permutation_cluster_1samp_test(-condition1, n_permutations=100,
                                            tail=-1, threshold=-1.67, seed=1,
                                            n_jobs=2)

        assert_array_equal(cluster_p_values_neg, cluster_p_values_neg_buff)


def test_cluster_permutation_with_connectivity():
    """Test cluster level permutations with connectivity matrix."""
    try:
        try:
            from sklearn.feature_extraction.image import grid_to_graph
        except ImportError:
            from scikits.learn.feature_extraction.image import grid_to_graph
    except ImportError:
        return

    n_pts = condition1_1d.shape[1]
    # we don't care about p-values in any of these, so do fewer permutations
    args = dict(seed=None, max_step=1, exclude=None,
                step_down_p=0, t_power=1, threshold=1.67,
                check_disjoint=False, n_permutations=50)

    for X1d, X2d, func, spatio_temporal_func in \
                [(condition1_1d, condition1_2d,
                  permutation_cluster_1samp_test,
                  spatio_temporal_cluster_1samp_test),
                  ([condition1_1d, condition2_1d],
                   [condition1_2d, condition2_2d],
                    permutation_cluster_test,
                    spatio_temporal_cluster_test)]:
        out = func(X1d, **args)
        connectivity = grid_to_graph(1, n_pts)
        out_connectivity = func(X1d, connectivity=connectivity, **args)
        assert_array_equal(out[0], out_connectivity[0])
        for a, b in zip(out_connectivity[1], out[1]):
            assert_array_equal(out[0][a], out[0][b])
            assert_true(np.all(a[b]))

        # test spatio-temporal w/o time connectivity (repeat spatial pattern)
        connectivity_2 = sparse.coo_matrix(
            linalg.block_diag(connectivity.asfptype().todense(),
                              connectivity.asfptype().todense()))

        if isinstance(X1d, list):
            X1d_2 = [np.concatenate((x, x), axis=1) for x in X1d]
        else:
            X1d_2 = np.concatenate((X1d, X1d), axis=1)

        out_connectivity_2 = func(X1d_2, connectivity=connectivity_2, **args)
        # make sure we were operating on the same values
        split = len(out[0])
        assert_array_equal(out[0], out_connectivity_2[0][:split])
        assert_array_equal(out[0], out_connectivity_2[0][split:])

        # make sure we really got 2x the number of original clusters
        n_clust_orig = len(out[1])
        assert_true(len(out_connectivity_2[1]) == 2 * n_clust_orig)

        # Make sure that we got the old ones back
        data_1 = set([np.sum(out[0][b[:n_pts]]) for b in out[1]])
        data_2 = set([np.sum(out_connectivity_2[0][a[:n_pts]]) for a in
            out_connectivity_2[1][:]])
        assert_true(len(data_1.intersection(data_2)) == len(data_1))

        # now use the other algorithm
        if isinstance(X1d, list):
            X1d_3 = [np.reshape(x, (-1, 2, 350)) for x in X1d_2]
        else:
            X1d_3 = np.reshape(X1d_2, (-1, 2, 350))

        out_connectivity_3 = spatio_temporal_func(
                                 X1d_3, n_permutations=50,
                                 connectivity=connectivity, max_step=0,
                                 threshold=1.67, check_disjoint=True)
        # make sure we were operating on the same values
        split = len(out[0])
        assert_array_equal(out[0], out_connectivity_3[0][0])
        assert_array_equal(out[0], out_connectivity_3[0][1])

        # make sure we really got 2x the number of original clusters
        assert_true(len(out_connectivity_3[1]) == 2 * n_clust_orig)

        # Make sure that we got the old ones back
        data_1 = set([np.sum(out[0][b[:n_pts]]) for b in out[1]])
        data_2 = set([np.sum(out_connectivity_3[0][a[0], a[1]]) for a in
            out_connectivity_3[1]])
        assert_true(len(data_1.intersection(data_2)) == len(data_1))

        # test new versus old method
        out_connectivity_4 = spatio_temporal_func(
                                 X1d_3, n_permutations=50,
                                 connectivity=connectivity, max_step=2,
                                 threshold=1.67)
        out_connectivity_5 = spatio_temporal_func(
                                 X1d_3, n_permutations=50,
                                 connectivity=connectivity, max_step=1,
                                 threshold=1.67)

        # clusters could be in a different order
        sums_4 = [np.sum(out_connectivity_4[0][a])
                  for a in out_connectivity_4[1]]
        sums_5 = [np.sum(out_connectivity_4[0][a])
                  for a in out_connectivity_5[1]]
        sums_4 = np.sort(sums_4)
        sums_5 = np.sort(sums_5)
        assert_array_almost_equal(sums_4, sums_5)

        assert_raises(ValueError, spatio_temporal_func,
                                 X1d_3, n_permutations=1,
                                 connectivity=connectivity, max_step=1,
                                 threshold=1.67, n_jobs=-1000)

        # not enough TFCE params
        assert_raises(KeyError, spatio_temporal_func, X1d_3,
                      connectivity=connectivity, threshold=dict(me='hello'))

        # too extreme a start threshold
        assert_raises(ValueError, spatio_temporal_func, X1d_3,
                      connectivity=connectivity,
                      threshold=dict(start=10, step=1))

        # too extreme a start threshold
        assert_raises(ValueError, spatio_temporal_func, X1d_3,
                      connectivity=connectivity, tail=-1,
                      threshold=dict(start=1, step=-1))
        assert_raises(ValueError, spatio_temporal_func, X1d_3,
                      connectivity=connectivity, tail=-1,
                      threshold=dict(start=-1, step=1))

        # wrong type for threshold
        assert_raises(TypeError, spatio_temporal_func, X1d_3,
                      connectivity=connectivity, threshold=[])

        # wrong value for tail
        assert_raises(ValueError, spatio_temporal_func, X1d_3,
                      connectivity=connectivity, tail=2)

        # make sure it actually found a significant point
        out_connectivity_6 = spatio_temporal_func(
                                 X1d_3, n_permutations=50,
                                 connectivity=connectivity, max_step=1,
                                 threshold=dict(start=1, step=1))
        assert_true(np.min(out_connectivity_6[2]) < 0.05)


def test_permutation_connectivity_equiv():
    """Test cluster level permutations with and without connectivity
    """
    try:
        try:
            from sklearn.feature_extraction.image import grid_to_graph
        except ImportError:
            from scikits.learn.feature_extraction.image import grid_to_graph
    except ImportError:
        return
    rng = np.random.RandomState(0)
    # subjects, time points, spatial points
    X = rng.randn(7, 2, 10)
    # add some significant points
    X[:, 0:2, 0:2] += 10  # span two time points and two spatial points
    X[:, 1, 5:9] += 10  # span four time points
    max_steps = [1, 1, 1, 2]
    # This will run full algorithm in two ways, then the ST-algorithm in 2 ways
    # All of these should give the same results
    conns = [None, grid_to_graph(2, 10),
             grid_to_graph(1, 10), grid_to_graph(1, 10)]
    stat_map = None
    thresholds = [2, dict(start=0.5, step=0.5)]
    sig_counts = [2, 8]
    for threshold, count in zip(thresholds, sig_counts):
        cs = None
        ps = None
        for max_step, conn in zip(max_steps, conns):
            for stat_fun in [ttest_1samp_no_p,
                             partial(ttest_1samp_no_p, sigma=1e-3)]:
                t, clusters, p, H0 = \
                        permutation_cluster_1samp_test(X, threshold=threshold,
                                                       connectivity=conn,
                                                       n_jobs=2,
                                                       max_step=max_step,
                                                       stat_fun=stat_fun)
                inds = np.where(p < 0.05)[0]
                assert_true(len(inds) == count)
                this_cs = [clusters[ii] for ii in inds]
                this_ps = p[inds]
                this_stat_map = np.zeros((2, 10), dtype=bool)
                for c in this_cs:
                    this_stat_map[c] = True
                if cs is None:
                    ps = this_ps
                    cs = this_cs
                if stat_map is None:
                    stat_map = this_stat_map
                assert_array_equal(ps, this_ps)
                assert_true(len(cs) == len(this_cs))
                for c1, c2 in zip(cs, this_cs):
                    assert_array_equal(c1, c2)
                assert_array_equal(stat_map, this_stat_map)


def ttest_1samp(X):
    """Returns T-values
    """
    return stats.ttest_1samp(X, 0)[0]
