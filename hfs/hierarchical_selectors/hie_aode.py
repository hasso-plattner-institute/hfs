import networkx as nx
import numpy as np
from sklearn.naive_bayes import BernoulliNB

from .lazyHierarchicalFeatureSelector import LazyHierarchicalFeatureSelector

SMOOTHING_FACTOR = 1
PRIOR_PROBABILITY = 0.5


class HieAODEBase(LazyHierarchicalFeatureSelector):
    """
    Select non-redundant features following the algorithm proposed by Wan and Freitas.
    """

    def __init__(self, hierarchy=None):
        """Initializes a HieAODE-Selector.

        Parameters
        ----------
        hierarchy : np.ndarray
            The hierarchy graph as an adjacency matrix.
        """
        self.cpts = dict()
        super(HieAODEBase, self).__init__(hierarchy)

    def fit_selector(self, X_train, y_train, X_test, columns=None):
        """
        P (y, x_i )
        class_prior

        self.n_ancestors = self._n_descendants = self.n_features_in_
        P (x_k|y)
        ancestors_class_cpt = (self.n_ancestors, self.n_classes, self.n_features_in, n_values)

        P (x_j|y, x_i)
        feature_descendants_class_cpt = (self.n_features_in, self._n_descendants, self.n_classes_, n_values)
        """
        super(HieAODEBase, self).fit_selector(X_train, y_train, X_test, columns)
        self.cpts = dict(
            # prior = P(y, x_i)
            prior=np.full(
                (self.n_features_in_, self.n_classes_, 2),  # x_i  # y  # value
                -1,
                dtype=float,
            ),
            # (x_j (descendent), x_i (current feature), class, value)  )
            prob_feature_given_class_and_parent=np.full(
                (self.n_features_in_, self.n_features_in_, self.n_classes_, 2, 2),
                -1,
                dtype=float,
            ),  # P(x_j|y, x_i)
            prob_feature_given_class=np.full(
                (self.n_features_in_, self.n_classes_, 2), -1, dtype=float
            ),  # P(x_k|y)
        )

    def select_and_predict(
        self, predict=True, saveFeatures=False, estimator=BernoulliNB()
    ):
        """
        Select features lazy for each test instance and optionally predict target value of test instances
        using the HieAODE algorithm by Wan and Freitas

        Parameters
        ----------
        predict : bool
            true if predictions shall be obtained.
        saveFeatures : bool
            true if features selected for each test instance shall be saved.
        estimator : sklearn-compatible estimator
            Estimator to use for predictions.


        Returns
        -------
        predictions for test input samples, if predict = false, returns empty array.
        """
        n_samples = self._xtest.shape[0]
        sample_sum = np.zeros((n_samples, self.n_classes_))
        for sample_idx in range(n_samples):
            sample = self._xtest[sample_idx]
            descendant_product = np.ones(self.n_classes_)
            ancestor_product = np.ones(self.n_classes_)
            for feature_idx in range(self.n_features_in_):
                ancestors = list(nx.ancestors(self._hierarchy, feature_idx))
                feature_product = np.multiply(
                    self.ancestors_product(sample=sample, ancestors=ancestors),
                    self.descendants_product(
                        sample=sample, feature_idx=feature_idx, ancestors=ancestors
                    ),
                )
                feature_product = np.multiply(
                    feature_product,
                    self.prior_term(sample=sample, feature_idx=feature_idx),
                )
                sample_sum[sample_idx] = np.add(sample_sum[sample_idx], feature_product)

        y = np.argmax(sample_sum, axis=1)
        return y if predict else np.array([])

    def prior_term(self, sample, feature_idx):
        self.calculate_class_prior(feature_idx=feature_idx)
        return np.prod(self.cpts["prior"][feature_idx, :, sample[feature_idx]])

    def ancestors_product(self, sample, ancestors, use_positive_only=False):
        # Calculate probabilities for each ancestor
        for ancestor_idx in ancestors:
            self.calculate_prob_feature_given_class(feature=ancestor_idx)
        # Handle case with no ancestors
        if len(ancestors) <= 0:
            return np.zeros(self.n_classes_)
        # Extract values for ancestors from the sample
        ancestors_value = sample[ancestors]
        # Extract corresponding CPT entries for the specific ancestors
        # and their values
        ancestors_cpt = self.cpts["prob_feature_given_class"][ancestors, :, ancestors_value]
        # If using only positive ancestors, filter the CPTs accordingly
        if use_positive_only and np.any(ancestors_value == 1):
            ancestors_cpt = ancestors_cpt[ancestors_value == 1]

        return np.prod(ancestors_cpt, axis=0)

    def descendants_product(self, sample, feature_idx, ancestors, use_positive_only=False):
        descendants = [
            feature
            for feature in range(self.n_features_in_)
            if feature != feature_idx and feature not in ancestors
        ]
        # P (x_j=sample[descendant_idx]|y, x_i=sample[feature_idx])
        for descendant_idx in descendants:
            self.calculate_prob_feature_given_class_and_parent(
                feature_idx=descendant_idx, parent_idx=feature_idx
            )
        if len(descendants) <= 0:
            return np.zeros(self.n_classes_)

        descendants_value = sample[descendants]
        feature_value = sample[feature_idx]
        descendants_cpt = self.cpts["prob_feature_given_class_and_parent"][
                descendants,
                feature_idx,
                :,
                feature_value,
                descendants_value,
            ]

        if use_positive_only and np.any(descendants_value == 1):
            descendants_cpt = descendants_cpt[descendants_value == 1]

        return np.prod(
            descendants_cpt,
            axis=0,
        )

    def descendants_product_negative(self, sample, feature_idx, ancestors):
        descendants = [
            feature
            for feature in range(self.n_features_in_)
            if feature != feature_idx and feature not in ancestors
        ]

        for descendant_idx in descendants:
            self.calculate_prob_feature_given_class(feature=descendant_idx)

        if len(descendants) <= 0:
            return np.zeros(self.n_classes_)

        descendants_value = sample[descendants]

        ancestors_cpt = self.cpts["prob_feature_given_class"][descendants, :, descendants_value]

        if np.any(descendants_value == 0):
            ancestors_cpt = ancestors_cpt[descendants_value == 0]
            return np.prod(ancestors_cpt, axis=0)
        else:
            return np.zeros(self.n_classes_)



    def calculate_class_prior(self, feature_idx):
        n_samples = self._ytrain.shape[0]
        for c in range(self.n_classes_):
            for value in range(2):
                if self.cpts["prior"][feature_idx][c][value] == -1:
                    value_sum = np.sum(
                        (self._ytrain == c) & (self._xtrain[:, feature_idx] == value)
                    )
                    self.cpts["prior"][feature_idx][c][value] = value_sum / n_samples

    def calculate_prob_feature_given_class(self, feature):
        # Calculate P(x_k | y) where x_k=ascendant and y = c
        for c in range(self.n_classes_):
            p_class = np.sum(self._ytrain == c)
            for value in range(2):
                p_class_ascendant = np.sum(
                    (self._ytrain == c) & (self._xtrain[:, feature] == value)
                )
                self.cpts["prob_feature_given_class"][feature][c][value] = (
                    p_class_ascendant + SMOOTHING_FACTOR * PRIOR_PROBABILITY
                ) / (p_class + SMOOTHING_FACTOR)

    def calculate_prob_feature_given_class_and_parent(
        self, feature_idx, parent_idx
    ):
        for c in range(self.n_classes_):
            for parent_value in range(2):
                # Calculate P(y, x_i = parent_value)
                mask = (self._xtrain[:, parent_idx] == parent_value) & (
                    self._ytrain == c
                )
                p_class_feature = np.sum(mask)
                for feature_value in range(2):
                    if feature_idx != parent_idx:
                        # Calculate P(y, x_i = parent_value, x_j = feature_value)
                        descendant = self._xtrain[:, feature_idx]
                        p_class_feature_descendant = np.sum(
                            descendant[mask] == feature_value
                        )
                        prob_descendant_given_c_feature = (
                            p_class_feature_descendant
                            + SMOOTHING_FACTOR * PRIOR_PROBABILITY
                        ) / (p_class_feature + SMOOTHING_FACTOR)

                        self.cpts["prob_feature_given_class_and_parent"][feature_idx][parent_idx][c][
                            feature_value
                        ][parent_value] = prob_descendant_given_c_feature


class HieAODE(HieAODEBase):
    def select_and_predict(
        self, predict=True, saveFeatures=False, estimator=BernoulliNB()
    ):
        """
        Select features lazy for each test instance and optionally predict target value of test instances
        using the HieAODE algorithm by Wan and Freitas

        Parameters
        ----------
        predict : bool
            true if predictions shall be obtained.
        saveFeatures : bool
            true if features selected for each test instance shall be saved.
        estimator : sklearn-compatible estimator
            Estimator to use for predictions.

        Returns
        -------
        predictions for test input samples, if predict = false, returns empty array.
        """
        n_samples = self._xtest.shape[0]
        sample_sum = np.zeros((n_samples, self.n_classes_))
        for sample_idx in range(n_samples):
            sample = self._xtest[sample_idx]
            descendant_product = np.ones(self.n_classes_)
            ancestor_product = np.ones(self.n_classes_)
            for feature_idx in range(self.n_features_in_):
                ancestors = list(nx.ancestors(self._hierarchy, feature_idx))
                feature_product = np.multiply(
                    self.ancestors_product(sample=sample, ancestors=ancestors),
                    self.descendants_product(
                        sample=sample, feature_idx=feature_idx, ancestors=ancestors
                    ),
                )
                feature_product = np.multiply(
                    feature_product,
                    self.prior_term(sample=sample, feature_idx=feature_idx),
                )
                sample_sum[sample_idx] = np.add(sample_sum[sample_idx], feature_product)

        y = np.argmax(sample_sum, axis=1)
        return y if predict else np.array([])


class HieAODELite(HieAODEBase):
    def select_and_predict(
        self, predict=True, saveFeatures=False, estimator=BernoulliNB()
    ):
        """
        Select features lazy for each test instance and optionally predict target value of test instances
        using the HieAODELite algorithm by Wan and Freitas

        Parameters
        ----------
        predict : bool
            true if predictions shall be obtained.
        saveFeatures : bool
            true if features selected for each test instance shall be saved.
        estimator : sklearn-compatible estimator
            Estimator to use for predictions.

        Returns
        -------
        predictions for test input samples, if predict = false, returns empty array.
        """
        n_samples = self._xtest.shape[0]
        sample_sum = np.zeros((n_samples, self.n_classes_))
        for sample_idx in range(n_samples):
            sample = self._xtest[sample_idx]
            descendant_product = np.ones(self.n_classes_)
            ancestor_product = np.ones(self.n_classes_)
            for feature_idx in range(self.n_features_in_):
                ancestors = list(nx.ancestors(self._hierarchy, feature_idx))
                feature_product = np.multiply(
                    self.descendants_product(
                        sample=sample, feature_idx=feature_idx, ancestors=ancestors
                    ),
                    self.prior_term(sample=sample, feature_idx=feature_idx),
                )
                sample_sum[sample_idx] = np.add(sample_sum[sample_idx], feature_product)

        y = np.argmax(sample_sum, axis=1)
        return y if predict else np.array([])


class HieAODE_plus(HieAODEBase):
    def select_and_predict(
        self, predict=True, saveFeatures=False, estimator=BernoulliNB()
    ):
        ...




class HieAODE_plus_plus(HieAODEBase):
    def select_and_predict(
            self, predict=True, saveFeatures=False, estimator=BernoulliNB()
    ):
        n_samples = self._xtest.shape[0]
        sample_sum = np.zeros((n_samples, self.n_classes_))
        for sample_idx in range(n_samples):
            sample = self._xtest[sample_idx]
            descendant_product = np.ones(self.n_classes_)
            ancestor_product = np.ones(self.n_classes_)
            for feature_idx in range(self.n_features_in_):
                ancestors = list(nx.ancestors(self._hierarchy, feature_idx))
                feature_product = np.multiply(
                    self.ancestors_product(sample=sample, ancestors=ancestors, use_positive_only=True),
                    self.descendants_product(
                        sample=sample, feature_idx=feature_idx, ancestors=ancestors, use_positive_only=True
                    ),
                )
                feature_product = np.multiply(
                    feature_product,
                    self.prior_term(sample=sample, feature_idx=feature_idx),
                )
                sample_sum[sample_idx] = np.add(sample_sum[sample_idx], feature_product)

        y = np.argmax(sample_sum, axis=1)
        return y if predict else np.array([])