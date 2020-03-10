#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf

from pykg2vec.core.KGMeta import ModelMeta, InferenceMeta


class TransR(ModelMeta, InferenceMeta):
    """ `Learning Entity and Relation Embeddings for Knowledge Graph Completion`_

        TranR is a translation based knowledge graph embedding method. Similar to TransE and TransH, it also
        builds entity and relation embeddings by regarding a relation as translation from head entity to tail
        entity. However, compared to them, it builds the entity and relation embeddings in a separate entity
        and relation spaces.

        Args:
            config (object): Model configuration parameters.

        Attributes:
            config (object): Model configuration.
            model_name (str): Name of the model.
            data_stats (object): Class object with knowlege graph statistics.

        Examples:
            >>> from pykg2vec.core.TransR import TransR
            >>> from pykg2vec.utils.trainer import Trainer
            >>> model = TransR()
            >>> trainer = Trainer(model=model, debug=False)
            >>> trainer.build_model()
            >>> trainer.train_model()

        Portion of the code based on `thunlp_transR`_.

         .. _thunlp_transR:
             https://github.com/thunlp/TensorFlow-TransX/blob/master/transR.py

        .. _Learning Entity and Relation Embeddings for Knowledge Graph Completion:
            http://nlp.csai.tsinghua.edu.cn/~lyk/publications/aaai2015_transr.pdf
    """

    def __init__(self, config):
        super(TransR, self).__init__()
        self.config = config
        self.model_name = 'TransR'

    def def_parameters(self):
        """Defines the model parameters.

          Attributes:
              num_total_ent (int): Total number of entities.
              num_total_rel (int): Total number of relations.
              k (Tensor): Size of the latent dimesnion for entities and relations.
              ent_embeddings (Tensor Variable): Lookup variable containing  embedding of the entities.
              rel_embeddings  (Tensor Variable): Lookup variable containing  embedding of the relations.
              rel_matrix   (Tensor Variable): Weight matrix for transformation of entity embeddings.
              parameter_list  (list): List of Tensor parameters.
        """
        num_total_ent = self.config.kg_meta.tot_entity
        num_total_rel = self.config.kg_meta.tot_relation
        k = self.config.ent_hidden_size
        d = self.config.rel_hidden_size

        emb_initializer = tf.initializers.glorot_normal()

        self.ent_embeddings = tf.Variable(emb_initializer(shape=(num_total_ent, k)), name="ent_embedding")
        self.rel_embeddings = tf.Variable(emb_initializer(shape=(num_total_rel, d)), name="rel_embedding")
        self.rel_matrix     = tf.Variable(emb_initializer(shape=(num_total_rel, k, d)), name="rel_matrix")
        
        self.parameter_list = [self.ent_embeddings, self.rel_embeddings, self.rel_matrix]

    def embed(self, h, r, t):
        """Function to get the embedding value.

           Args:
               h (Tensor): Head entities ids.
               r (Tensor): Relation ids of the triple.
               t (Tensor): Tail entity ids of the triple.

            Returns:
                Tensors: Returns head, relation and tail embedding Tensors.
        """
        h_e = tf.nn.embedding_lookup(self.ent_embeddings, h)
        r_e = tf.nn.embedding_lookup(self.rel_embeddings, r)
        t_e = tf.nn.embedding_lookup(self.ent_embeddings, t)
        
        h_e = tf.nn.l2_normalize(h_e, axis=-1)
        r_e = tf.nn.l2_normalize(r_e, axis=-1)
        t_e = tf.nn.l2_normalize(t_e, axis=-1)

        h_e = tf.expand_dims(h_e, axis=1)
        t_e = tf.expand_dims(t_e, axis=1)
        # [b, 1, k]

        matrix = tf.nn.embedding_lookup(self.rel_matrix, r)
        # [b, k, d]

        transform_h_e = tf.matmul(h_e, matrix)
        transform_t_e = tf.matmul(t_e, matrix)
        # [b, d, 1] = [b, 1, k] * [b, k, d]

        h_e = tf.squeeze(transform_h_e, axis=1)
        t_e = tf.squeeze(transform_t_e, axis=1)
        # [b, d]
        return h_e, r_e, t_e

    def dissimilarity(self, h, r, t, axis=-1):
        """Function to calculate distance measure in embedding space.
        
        if used in def_loss,
            h, r, t shape [b, k], return shape will be [b]
        if used in test_batch, 
            h, r, t shape [1, tot_ent, k] or [b, 1, k], return shape will be [b, tot_ent]

        Args:
            h (Tensor): shape [b, k] Head entities in a batch. 
            r (Tensor): shape [b, k] Relation entities in a batch.
            t (Tensor): shape [b, k] Tail entities in a batch.
            axis (int): Determines the axis for reduction

        Returns:
            Tensor: shape [b] the aggregated distance measure.
        """
        norm_h = tf.nn.l2_normalize(h, axis=axis)
        norm_r = tf.nn.l2_normalize(r, axis=axis)
        norm_t = tf.nn.l2_normalize(t, axis=axis)
        
        dissimilarity = norm_h + norm_r - norm_t 

        if self.config.L1_flag:
            dissimilarity = tf.math.abs(dissimilarity) # L1 norm 
        else:
            dissimilarity = tf.math.square(dissimilarity) # L2 norm
        
        return tf.reduce_sum(dissimilarity, axis=axis)

    def get_loss(self, pos_h, pos_r, pos_t, neg_h, neg_r, neg_t):
        """Defines the loss function for the algorithm."""
        pos_h_e, pos_r_e, pos_t_e = self.embed(pos_h, pos_r, pos_t)
        pos_score = self.dissimilarity(pos_h_e, pos_r_e, pos_t_e)

        neg_h_e, neg_r_e, neg_t_e = self.embed(neg_h, neg_r, neg_t)
        neg_score = self.dissimilarity(neg_h_e, neg_r_e, neg_t_e)

        loss = self.pairwise_margin_loss(pos_score, neg_score)

        return loss

    def predict(self, h, r, t, topk=-1):

        """Function that performs prediction for TransE. 
           shape of h can be either [num_tot_entity] or [1]. 
           shape of t can be either [num_tot_entity] or [1].

          Returns:
              Tensors: Returns ranks of head and tail.
        """
        h_e, r_e, t_e = self.embed(h, r, t)
        score = self.dissimilarity(h_e, r_e, t_e)
        _, rank = tf.nn.top_k(score, k=topk)

        return rank

    def test_batch(self, h_batch, r_batch, t_batch):
        """Function that performs batch testing for the algorithm.

             Returns:
                 Tensors: Returns ranks of head and tail.
        """
        head_vec, rel_vec, tail_vec = self.embed(h_batch, r_batch, t_batch)

        k = self.config.ent_hidden_size
        d = self.config.rel_hidden_size
        b = self.config.batch_size_testing

        pos_matrix = tf.nn.embedding_lookup(self.rel_matrix, r_batch)
        # [b, k, d]
        pos_matrix = tf.transpose(pos_matrix, perm=[0, 2, 1])
        # [b, d, k]
        pos_matrix = tf.reshape(pos_matrix, [-1, k])
        # [b*d, k]

        project_ent_embedding = tf.matmul(tf.nn.l2_normalize(self.ent_embeddings, axis=-1), pos_matrix, transpose_b=True)
        # [14951, b*d] = [14951, k], [k, b*d]

        project_ent_embedding = tf.reshape(project_ent_embedding,[-1, b, d])
        # [14951, b, d]

        project_ent_embedding = tf.transpose(project_ent_embedding, perm=[1, 0, 2])
        # [b, 14951, d]

        score_head = self.dissimilarity(project_ent_embedding,
                                        tf.expand_dims(rel_vec, axis=1),
                                        tf.expand_dims(tail_vec, axis=1))
        score_tail = self.dissimilarity(tf.expand_dims(head_vec, axis=1),
                                        tf.expand_dims(rel_vec, axis=1),
                                        project_ent_embedding)

        _, head_rank = tf.nn.top_k(score_head, k=self.config.kg_meta.tot_entity)
        _, tail_rank = tf.nn.top_k(score_tail, k=self.config.kg_meta.tot_entity)

        return head_rank, tail_rank