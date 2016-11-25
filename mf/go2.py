from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import math
import os, shutil
import random
import sys
import time
import logging

import numpy as np
from six.moves import xrange  # pylint: disable=redefined-builtin
import tensorflow as tf
# from load_data import *    
from recsys_data import data_read

import mf_model2
from eval2 import *
from submit import *

# in order to profile
# from tensorflow.python.client import timeline

tf.app.flags.DEFINE_float("learning_rate", 0.5, "Learning rate.")
tf.app.flags.DEFINE_float("keep_prob", 0.5, "dropout rate.")
tf.app.flags.DEFINE_float("learning_rate_decay_factor", 0.99,
													"Learning rate decays by this much.")
tf.app.flags.DEFINE_float("max_gradient_norm", 5.0,
													"Clip gradients to this norm.")
tf.app.flags.DEFINE_integer("batch_size", 64,
														"Batch size to use during training.")
tf.app.flags.DEFINE_integer("size", 100, "Size of each model layer.")
tf.app.flags.DEFINE_integer("num_layers", 1, "Number of layers in the model.")
tf.app.flags.DEFINE_integer("user_vocab_size", 150000, "User vocabulary size.")
tf.app.flags.DEFINE_integer("item_vocab_size", 50000, "Item vocabulary size.")
tf.app.flags.DEFINE_string("data_dir", "/tmp", "Data directory")
tf.app.flags.DEFINE_string("train_dir", "/tmp", "Training directory.")
tf.app.flags.DEFINE_integer("max_train_data_size", 0,
														"Limit on the size of training data (0: no limit).")
tf.app.flags.DEFINE_integer("steps_per_checkpoint", 100,
														"How many training steps to do per checkpoint.")
tf.app.flags.DEFINE_boolean("use_item_feature", True,
														"Set to True to use item features.")
tf.app.flags.DEFINE_boolean("recommend", False,
														"Set to True for recommend items.")
tf.app.flags.DEFINE_boolean("recommend_new", False,
														"Set to True for recommend new items that were not used to train.")
tf.app.flags.DEFINE_boolean("device_log", False,
														"Set to True for logging device usages.")
tf.app.flags.DEFINE_boolean("eval", False,
														"Set to True for evaluation.")
tf.app.flags.DEFINE_integer("top_N_items", 35,
														"number of items output")
tf.app.flags.DEFINE_string("loss", 'ce',
														"loss function")
tf.app.flags.DEFINE_string("model_option", 'loss',
														"model to evaluation")
tf.app.flags.DEFINE_string("log", 'log/log0', "logfile")
tf.app.flags.DEFINE_string("nonlinear", 'linear', "nonlinear activation")
tf.app.flags.DEFINE_integer("gpu", -1, "gpu card number")

FLAGS = tf.app.flags.FLAGS


def read_data():
	(data_tr, data_va, u_attr, i_attr, item_ind2logit_ind, 
    logit_ind2item_ind) = data_read(FLAGS.data_dir, _submit = 0, ta = 1, 
    logits_size_tr=FLAGS.item_vocab_size)
	return (data_tr, data_va, u_attr, i_attr, item_ind2logit_ind, 
    logit_ind2item_ind)

def create_model(session, u_attributes=None, i_attributes=None, 
	item_ind2logit_ind=None, logit_ind2item_ind=None, 
	loss = FLAGS.loss, logit_size_test=None):	
	gpu = None if FLAGS.gpu == -1 else FLAGS.gpu
	model = mf_model2.LatentProductModel(FLAGS.user_vocab_size, 
		FLAGS.item_vocab_size, FLAGS.size, FLAGS.num_layers, 
		FLAGS.max_gradient_norm, FLAGS.batch_size, FLAGS.learning_rate, 
		FLAGS.learning_rate_decay_factor, u_attributes, i_attributes, 
		item_ind2logit_ind, logit_ind2item_ind, loss_function = loss, GPU=gpu, 
		logit_size_test=logit_size_test, nonlinear=FLAGS.nonlinear, 
		dropout=FLAGS.keep_prob)

	if not os.path.isdir(FLAGS.train_dir):
		os.mkdir(FLAGS.train_dir)
	ckpt = tf.train.get_checkpoint_state(FLAGS.train_dir)
	if FLAGS.recommend and ckpt:
		print("%s" % ckpt.model_checkpoint_path)
		if FLAGS.model_option == 'loss':
			f = os.path.join(FLAGS.train_dir, 'go.ckpt-best')
		elif FLAGS.model_option == 'auc':
			f = os.path.join(FLAGS.train_dir, 'go.ckpt-best_auc')
		else:
			print("no such models %s" % FLAGS.model_option)
			exit()
		ckpt.model_checkpoint_path = f
		print("Reading model parameters from %s" % ckpt.model_checkpoint_path)
		logging.info("Reading model parameters from %s" % ckpt.model_checkpoint_path)
		model.saver.restore(session, ckpt.model_checkpoint_path)

	elif ckpt and tf.gfile.Exists(ckpt.model_checkpoint_path):
		print("Reading model parameters from %s" % ckpt.model_checkpoint_path)
		logging.info("Reading model parameters from %s" % ckpt.model_checkpoint_path)
		model.saver.restore(session, ckpt.model_checkpoint_path)
	else:
		print("Created model with fresh parameters.")
		logging.info("Created model with fresh parameters.")
		session.run(tf.initialize_all_variables())
	return model

def train():
	with tf.Session(config=tf.ConfigProto(log_device_placement=FLAGS.device_log)) as sess:
		# run_options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
		# run_metadata = tf.RunMetadata()
		# sess.run(res, options=run_options, run_metadata=run_metadata)

		print("reading data")
		logging.info("reading data")
		(data_train, data_valid, u_attributes, i_attributes,item_ind2logit_ind, 
			logit_ind2item_ind) = read_data()
		print("original train/dev size: %d/%d" %(len(data_train),len(data_valid)))
		logging.info("original train/dev size: %d/%d" %(len(data_train),len(data_valid)))
		data_tr = [(p[0], item_ind2logit_ind[p[1]]) for p in data_train if (
			item_ind2logit_ind[p[1]] != 0)]
		data_va = [(p[0], item_ind2logit_ind[p[1]]) for p in data_valid if (
			item_ind2logit_ind[p[1]] != 0)]
		print("new train/dev size: %d/%d" %(len(data_tr),len(data_va)))
		logging.info("new train/dev size: %d/%d" %(len(data_tr),len(data_va)))
		hist, hist_va = {}, {}
		for u, i in data_tr:
			if u not in hist:
				hist[u] = set([i])
			else:
				hist[u].add(i)
		for u, i in data_va:
			if u not in hist_va:
				hist_va[u] = set([i])
			else:
				hist_va[u].add(i)

		# indices_logits = range(len(item_ind2logit_ind))
		indices_logits = range(len(logit_ind2item_ind))

		# print("debugging..")
		if FLAGS.use_item_feature:
			print("using item attributes")
			logging.info("using item attributes")
		else:
			print("NOT using item attributes")
			logging.info("NOT using item attributes")
			i_attributes.num_features_mulhot = 0
			u_attributes.num_features_mulhot = 0
			# i_attributes.num_features_cat = 1
		print("completed")
		logging.info("completed")

		model = create_model(sess, u_attributes, i_attributes, item_ind2logit_ind,
			logit_ind2item_ind, loss=FLAGS.loss)

		pos_item_list, pos_item_list_withval = None, None
		pos_item_list_val = None
		if FLAGS.loss == 'warp':
			pos_item_list, pos_item_list_withval = {}, {}
			pos_item_list_val = {}
			for u in hist:
				pos_item_list[u] = list(hist[u])
			for u in hist_va:
				pos_item_list_val[u] = list(hist_va[u])

			u_set = set(hist.keys() + hist_va.keys())
			for u in u_set:
				if u in hist and u in hist_va:
					pos_item_list_withval[u] = list(hist[u].union(hist_va[u]))
				elif u in hist:
					pos_item_list_withval[u] = list(hist[u])
				elif u in hist_va:
					pos_item_list_withval[u] = list(hist_va[u])
				else:
					logging.error('wrong')
					print('wrong')
					exit(-1)
			# model.prepare_warp(pos_item_list, pos_item_list_withval)		
			model.prepare_warp(pos_item_list, pos_item_list_val)

		# for var in tf.all_variables():
		# 	print(var.name)

		print('started training')
		logging.info('started training')
		step_time, loss, current_step, auc = 0.0, 0.0, 0, 0.0
		
		repeat = 5 if FLAGS.loss.startswith('bpr') else 1
		
		patience = 10

		if os.path.isfile(os.path.join(FLAGS.train_dir, 'auc_train.npy')):
			auc_train = list(np.load(os.path.join(FLAGS.train_dir, 'auc_train.npy')))
			auc_dev = list(np.load(os.path.join(FLAGS.train_dir, 'auc_dev.npy')))
			previous_losses = list(np.load(os.path.join(FLAGS.train_dir, 
				'loss_train.npy')))
			losses_dev = list(np.load(os.path.join(FLAGS.train_dir, 'loss_dev.npy')))
			best_auc = max(auc_dev)
			best_loss = min(losses_dev)
		else:
			previous_losses, auc_train, auc_dev, losses_dev = [], [], [], []
			best_auc, best_loss = -1, 1000000

		while True:
			ranndom_number_01 = np.random.random_sample()
			start_time = time.time()
			user_input, item_input, neg_item_input = model.get_batch(data_tr, 
				hist=hist)
			step_loss, step_auc, negs, pos = model.step(sess, user_input, item_input, 
				neg_item_input, loss=FLAGS.loss)
			# step_loss, step_auc, negs, pos = model.step(sess, user_input, item_input, 
			# 	neg_item_input, loss=FLAGS.loss, run_op = run_options, 
			# 	run_meta = run_metadata)	
			step_time += (time.time() - start_time) / FLAGS.steps_per_checkpoint
			loss += step_loss / FLAGS.steps_per_checkpoint
			auc += step_auc / FLAGS.steps_per_checkpoint
			current_step += 1
			
			if current_step % FLAGS.steps_per_checkpoint == 0:

				if FLAGS.loss in ['ce']:
					perplexity = math.exp(loss) if loss < 300 else float('inf')
					print ("global step %d learning rate %.4f step-time %.2f perplexity %.2f auc %.2f" % (model.global_step.eval(), model.learning_rate.eval(), step_time, perplexity, auc))
					logging.info ("global step %d learning rate %.4f step-time %.2f perplexity %.2f auc %.2f" % (model.global_step.eval(), model.learning_rate.eval(), step_time, perplexity, auc))
				# elif FLAGS.loss == 'bpr':
				else:
					print ("global step %d learning rate %.4f step-time %.2f loss %.3f auc %.4f" % (model.global_step.eval(), model.learning_rate.eval(), step_time, loss, auc))
					logging.info ("global step %d learning rate %.4f step-time %.2f loss %.3f auc %.4f" % (model.global_step.eval(), model.learning_rate.eval(), step_time, loss, auc))
				# Create the Timeline object, and write it to a json
				# tl = timeline.Timeline(run_metadata.step_stats)
				# ctf = tl.generate_chrome_trace_format()
				# with open('timeline.json', 'w') as f:
				#     f.write(ctf)
				# exit()

				# Decrease learning rate if no improvement was seen over last 3 times.
				if len(previous_losses) > 2 and loss > max(previous_losses[-3:]):
					sess.run(model.learning_rate_decay_op) 
				previous_losses.append(loss)
				auc_train.append(auc)
				step_time, loss, auc = 0.0, 0.0, 0.0

				if not FLAGS.eval:
					continue
				# Save checkpoint and zero timer and loss.
				checkpoint_path = os.path.join(FLAGS.train_dir, "go.ckpt")
				current_model = model.saver.save(sess, checkpoint_path, global_step=model.global_step)
				
				# Run evals on development set and print their loss/auc.
				l_va = len(data_va)
				eval_loss, eval_auc = 0.0, 0.0
				count_va = 0
				start_time = time.time()
				for idx_s in range(0, l_va, FLAGS.batch_size):
					idx_e = idx_s + FLAGS.batch_size
					if idx_e > l_va:
						break
					lt = data_va[idx_s:idx_e]
					user_va = [x[0] for x in lt]
					item_va = [x[1] for x in lt]
					for _ in range(repeat):
						item_va_neg = []
						for indu in range(len(item_va)):
							uind = user_va[indu]
							i2 = random.choice(indices_logits)
							while True:
								if uind in hist_va:
									if i2 in hist_va[uind]:
										i2 = random.choice(indices_logits)
										continue
								if uind in hist:
									if i2 in hist[uind]:
										i2 = random.choice(indices_logits)
										continue
								break
							item_va_neg.append(i2)

						eval_loss0, auc0 = model.step(sess, user_va, item_va, item_va_neg,
							forward_only=True, loss=FLAGS.loss)
						eval_loss += eval_loss0
						eval_auc += auc0
						count_va += 1
				eval_loss /= count_va
				eval_auc /= count_va
				step_time = (time.time() - start_time) / count_va
				if FLAGS.loss == 'ce':
					eval_ppx = math.exp(eval_loss) if eval_loss < 300 else float('inf')
					print("  eval: perplexity %.2f eval_auc %.4f step-time %.2f" % (
						eval_ppx, eval_auc, step_time))
					logging.info("  eval: perplexity %.2f eval_auc %.4f step-time %.2f" % (
						eval_ppx, eval_auc, step_time))
				else:
					print("  eval: loss %.3f eval_auc %.4f step-time %.2f" % (eval_loss, 
						eval_auc, step_time))
					logging.info("  eval: loss %.3f eval_auc %.4f step-time %.2f" % (eval_loss, 
						eval_auc, step_time))
				sys.stdout.flush()

				if eval_auc > best_auc:
					best_auc = eval_auc
					new_filename = os.path.join(FLAGS.train_dir, "go.ckpt-best_auc")
					shutil.copy(current_model, new_filename)
					patience = 50
				
				if eval_loss < best_loss:
					best_loss = eval_loss
					new_filename = os.path.join(FLAGS.train_dir, "go.ckpt-best")
					shutil.copy(current_model, new_filename)
					patience = 50

				if eval_loss > best_loss and eval_auc > best_auc:
					patience -= 1

				auc_dev.append(eval_auc)
				losses_dev.append(eval_loss)

				np.save(os.path.join(FLAGS.train_dir, 'auc_train'), auc_train)
				np.save(os.path.join(FLAGS.train_dir, 'auc_dev'), auc_dev)
				np.save(os.path.join(FLAGS.train_dir, 'loss_train'), previous_losses)
				np.save(os.path.join(FLAGS.train_dir, 'loss_dev'), losses_dev)

				if patience < 0:
					print("no improvement on auc for too long.. terminating..")
					print("best auc %.4f" % best_auc)
					print("best loss %.4f" % best_loss)
					logging.info("no improvement on auc for too long.. terminating..")
					logging.info("best auc %.4f" % best_auc)
					logging.info("best loss %.4f" % best_loss)
					sys.stdout.flush()
					break

	return

def recommend():

	with tf.Session() as sess:
		print("reading data")
		# logging.info("reading data")
		(data_tr, data_va, u_attributes, i_attributes, item_ind2logit_ind, 
			logit_ind2item_ind) = read_data()
		print("completed")
		# logging.info("completed")

		print("original train/dev size: %d/%d" %(len(data_tr),len(data_va)))
		# logging.info("original train/dev size: %d/%d" %(len(data_tr),len(data_va)))
		data_tr = [p for p in data_tr if item_ind2logit_ind[p[1]] != 0]
		data_va = [p for p in data_va if item_ind2logit_ind[p[1]] != 0]
		print("new train/dev size: %d/%d" %(len(data_tr),len(data_va)))
		# logging.info("new train/dev size: %d/%d" %(len(data_tr),len(data_va)))

		N = len(item_ind2logit_ind)

		cum_loss, count = 0.0, 0
		
		T = load_submit('../submissions/res_T.csv')
		print("length of active users in eval week: %d" % len(T))
		# logging.info("length of active users in eval week: %d" % len(T))
		
		from load_data import load_user_target_csv, load_item_active_csv
		Uatt, user_feature_names, Uid2ind = load_user_target_csv()
		Iatt, item_feature_names, Iid2ind = load_item_active_csv()

		model = create_model(sess, u_attributes, i_attributes, item_ind2logit_ind,
			logit_ind2item_ind, loss=FLAGS.loss, logit_size_test=len(Iatt))

		Uids = list(T.keys())
		Uinds = [Uid2ind[v] for v in Uids]
		N = len(Uinds)
		# N = 10000
		rec = np.zeros((N, 30), dtype=int)

		print("N = %d" % N)
		# logging.info("N = %d" % N)
		
		items_ = [0] * FLAGS.batch_size
		time_start = time.time()
		for idx_s in range(0, N, FLAGS.batch_size):
			count += 1
			if count % 100 == 0:
				print("idx: %d, c: %d" % (idx_s, count))
				# logging.info("idx: %d, c: %d" % (idx_s, count))
			idx_e = idx_s + FLAGS.batch_size
			if idx_e <= N:

				users = Uinds[idx_s: idx_e]
				recs = model.step(sess, users, items_, items_, forward_only=True, 
					recommend = True, recommend_new = FLAGS.recommend_new)
				
				rec[idx_s:idx_e, :] = recs
			else:
				users = range(idx_s, N) + [0] * (idx_e - N)
				users = [Uinds[t] for t in users]

				recs = model.step(sess, users, items_, items_, forward_only=True, 
					recommend = True, recommend_new = FLAGS.recommend_new)
				idx_e = N
				rec[idx_s:idx_e, :] = recs[:(idx_e-idx_s),:]
		time_end = time.time()
		print("Time used %.1f" % (time_end - time_start))
		logging.info("Time used %.1f" % (time_end - time_start))

		R = {}
		if not FLAGS.recommend_new:
			for i in xrange(N):
				uid = Uatt[Uinds[i], 0]
				R[uid] = [Iatt[logit_ind2item_ind[logid], 0] for logid in list(rec[i, :])]
		else:				
			for i in xrange(N):
				uid = Uatt[Uinds[i], 0]
				R[uid] = [Iatt[logid, 0] for logid in list(rec[i, :])]
		# filename = os.path.join(FLAGS.train_dir, 'rec')
		filename = 'rec'
		format_submit(R, filename)
		R2 = load_submit(filename)		
		print(scores(R2, T))
		logging.info(scores(R2, T))
		from eval_rank import eval_P5, eval_R20
		print("R20")
		logging.info("R20")
		r20 = eval_R20(R2, T)
		print(r20)
		logging.info(r20)
		print("P5")
		logging.info("P5")
		p5 = eval_P5(R2, T)
		print(p5)
		logging.info(p5)

	return


def main(_):
	logging.basicConfig(filename=FLAGS.log,level=logging.DEBUG)
	# logging.debug('This message should go to the log file')
	# logging.info('So should this')
	# logging.warning('And this, too')

	if not FLAGS.recommend:
		train()
	else:
		recommend()
	return

if __name__ == "__main__":
		tf.app.run()

