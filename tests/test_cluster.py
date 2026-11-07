import unittest

from heimdall import cluster


class TestCluster(unittest.TestCase):
    def test_kmeans_two_blobs(self) -> None:
        pts = [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (10.0, 10.0), (10.0, 11.0), (11.0, 10.0)]
        lab, cent = cluster.kmeans(pts, [1.0] * 6, 2)
        self.assertEqual(len(cent), 2)
        self.assertEqual(cluster._compact(lab), [0, 0, 0, 1, 1, 1])

    def test_silhouette_good_vs_bad(self) -> None:
        pts = [(0.0,), (1.0,), (10.0,), (11.0,)]
        w = [1.0] * 4
        good = cluster.silhouette(pts, w, [0, 0, 1, 1])
        bad = cluster.silhouette(pts, w, [0, 1, 0, 1])
        self.assertGreater(good, 0.8)
        self.assertLess(bad, 0)
        self.assertEqual(cluster.silhouette(pts, w, [0, 0, 0, 0]), -1.0)

    def test_run_kmeans_picks_k2(self) -> None:
        rows = [(0.0, 0.0)] * 5 + [(1.0, 0.0)] * 5 + [(20.0, 20.0)] * 5 + [(21.0, 20.0)] * 5
        out = cluster.run_kmeans(rows)
        self.assertEqual(out["distinct"], 4)
        runs = out["runs"]
        self.assertEqual([r["k"] for r in runs], [2, 4])
        self.assertEqual(runs[out["default"]]["k"], 2)

    def test_affinity_blobs(self) -> None:
        pts = [(0.0, 0.0), (0.2, 0.0), (0.0, 0.2), (9.0, 9.0), (9.2, 9.0), (9.0, 9.2)]
        lab = cluster.affinity(pts, [1.0] * 6)
        self.assertEqual(lab[0], lab[1])
        self.assertEqual(lab[0], lab[2])
        self.assertEqual(lab[3], lab[4])
        self.assertNotEqual(lab[0], lab[3])

    def test_affinity_slow_start(self) -> None:
        # Fixed point: with damping 0.9 the messages stay in the one-exemplar start-up state for
        # about 190 iterations on these points. The old rule (exemplar set unchanged for 15
        # iterations) stopped there and returned one cluster; the run to convergence gives two.
        pts = [(2.9, 9.3), (9.5, 7.8), (6.1, 8.0), (0.5, 6.2), (4.5, 3.3)]
        lab = cluster.affinity(pts, [9.0, 5.0, 5.0, 1.0, 5.0])
        self.assertGreater(len(set(lab)), 1)
        self.assertEqual(len(set(lab)), len(set(cluster.affinity(pts, [1.0] * 5, iters=3000))))

    def test_affinity_cap(self) -> None:
        rows = [(float(i), 0.0) for i in range(cluster.AP_CAP + 20)]
        out = cluster.run_affinity(rows)
        self.assertTrue(out["capped"])
        self.assertEqual(len(out["labels"]), len(rows))

    def test_single(self) -> None:
        self.assertEqual(cluster.affinity([(1.0,)], [1.0]), [0])
        self.assertEqual(cluster.run_kmeans([(1.0,)] * 3)["runs"], [])


if __name__ == "__main__":
    unittest.main()
