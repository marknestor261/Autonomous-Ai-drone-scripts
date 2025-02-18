# network file. Based on donkeycar keras.py file.
# %%

import imp
import os
import numpy as np

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import models
from tensorflow.keras import layers
from tensorflow.keras.applications import InceptionV3, VGG16
from keras_pos_embd import PositionEmbedding

#from positional_encodings import PositionalEncodingPermute1D 

"""
Inception/MobileNet -> Transformer (one-image) -> LSTM

Inception/MobileNet(t) --\
Inception/MobileNet(t-1) --> Transformer (multi-image features)

Real Encoder (positional encoding) {8,256} --\
Inception/MobileNet(t-1) -----------------------> (concat,-2{8*k+n*3,256})---> Transformer (8+n,256)[0] -> MLP{1,4}

Real Encoder (positional encoding) {8,256} ---(concat,-2{8*k+n*3,256})---> Transformer (8+n,256)[0] -> MLP{1,4}
Inception/MobileNet(t){n,256} --------------/
Inception/MobileNet(t-1){n,256} -----------/
Inception/MobileNet(t-2){n,256} ----------/
"""


class TransformerBlock(layers.Layer):
    def __init__(self, embed_dim, num_heads, ff_dim, rate=0.1):
        super(TransformerBlock, self).__init__()
        self.att = layers.MultiHeadAttention(num_heads=num_heads, key_dim=embed_dim)
        self.ffn = keras.Sequential(
            [layers.Dense(ff_dim, activation="relu"), layers.Dense(embed_dim),]
        )
        self.layernorm1 = layers.LayerNormalization(epsilon=1e-6)
        self.layernorm2 = layers.LayerNormalization(epsilon=1e-6)
        self.dropout1 = layers.Dropout(rate)
        self.dropout2 = layers.Dropout(rate)

    def call(self, inputs, training):
        attn_output = self.att(inputs, inputs)
        attn_output = self.dropout1(attn_output, training=training)
        out1 = self.layernorm1(inputs + attn_output)
        ffn_output = self.ffn(out1)
        ffn_output = self.dropout2(ffn_output, training=training)
        return self.layernorm2(out1 + ffn_output)

class TokenAndPositionEmbedding(layers.Layer):
    def __init__(self, maxlen, embed_dim):
        super(TokenAndPositionEmbedding, self).__init__()
        self.pos_emb = layers.Embedding(input_dim=maxlen, output_dim=embed_dim, input_length=10)

    def call(self, x):
        maxlen = tf.shape(x)[-1]
        positions = tf.range(start=0, limit=maxlen, delta=1) # [1...8]
        positions = self.pos_emb(positions)
        return positions

def create_transformer_model(latent_dim=256):
    
    base_model = InceptionV3(weights='imagenet', include_top=False, input_shape=(300, 300, 3), pooling='avg')
    image_input = layers.Input(shape=(300, 300, 3), name='image')

    x = base_model(image_input)
    x = layers.Dense(latent_dim, activation='relu')(x)
    x = keras.layers.Reshape((1,latent_dim), input_shape=(latent_dim,))(x)

    #targetdistance, pathdistance, headingdelta, speed, altitude, x, y, z
    # Input(shape(8, 256)) # 1500 -> [0.5, 0.1, 0.3, 0.1 0.6] # 0.5 -> [0.1, 0.1]
    maxlen = 8
    metadata = layers.Input(shape=(maxlen,latent_dim), name="path_distance_in")

    z = layers.Concatenate(axis=1)([metadata,x])

    pos_emb = PositionEmbedding(
        input_shape=(None,),
        input_dim=10,     # The maximum absolute value of positions.
        output_dim=latent_dim,     # The dimension of embeddings.
        mask_zero=10000,  # The index that presents padding (because `0` will be used in relative positioning).
        mode=PositionEmbedding.MODE_ADD,
    )
    #emb_td = TokenAndPositionEmbedding(maxlen+1, 256)
    z = pos_emb(z) 

    z = TransformerBlock(latent_dim, 2, 32)(z)
    
    #y = layers.Embedding(input_dim=2000, output_dim=256, input_length=8)
    z = layers.Dense(128, activation='relu')(z[:,0])
    z = layers.Dropout(.1)(z)
    z = layers.Dense(128, activation='relu')(z)
    z = layers.Dropout(.1)(z)

    outputs = []  # will be throttle, yaw, pitch, roll

    for i in range(4):
        a = layers.Dense(64, activation='relu')(z)
        a = layers.Dropout(.1)(a)
        a = layers.Dense(64, activation='relu')(a)
        a = layers.Dropout(.1)(a)
        a = layers.Dense(64, activation='relu')(a)
        a = layers.Dropout(.1)(a)
        a = layers.Dense(64, activation='relu')(a)
        a = layers.Dropout(.1)(a)
        outputs.append(layers.Dense(1, activation='sigmoid', name='out_' + str(i))(a)) #sigmoid

    model = models.Model(inputs=[image_input,metadata], outputs=outputs)

    return model, base_model


def create_transfer_model():

    base_model = InceptionV3(weights='imagenet', include_top=False, input_shape=(300, 300, 3), pooling='avg')
    #base_model = VGG16(weights='imagenet',include_top=False,input_shape=(300, 300, 3))
    image_input = layers.Input(shape=(300, 300, 3), name='image')
    x = base_model(image_input)
    x = layers.Dense(256, activation='relu')(x)

    #targetdistance, pathdistance, headingdelta, speed, altitude, x, y, z
    # Input(shape(8, 256)) # 1500 -> [0.5, 0.1, 0.3, 0.1 0.6] # 0.5 -> [0.1, 0.1]
    metadata = layers.Input(shape=(8,), name="path_distance_in")

    y = metadata
    y = layers.Dense(14, activation='relu')(y)
    y = layers.Dense(28, activation='relu')(y)
    y = layers.Dense(56, activation='relu')(y)
    
    print(y.shape)
    z = layers.concatenate([x, y])
    z = layers.Dense(128, activation='relu')(z)
    z = layers.Dropout(.1)(z)
    z = layers.Dense(128, activation='relu')(z)
    z = layers.Dropout(.1)(z)

    outputs = []  # will be throttle, yaw, pitch, roll

    #for i in range(4):
    #    outputs.append(layers.Dense(1, activation='sigmoid', name='out_' + str(i))(z)) #sigmoid

    for i in range(4):
        a = layers.Dense(64, activation='relu')(z)
        a = layers.Dropout(.1)(a)
        a = layers.Dense(64, activation='relu')(a)
        a = layers.Dropout(.1)(a)
        a = layers.Dense(64, activation='relu')(a)
        a = layers.Dropout(.1)(a)
        a = layers.Dense(64, activation='relu')(a)
        a = layers.Dropout(.1)(a)
        outputs.append(layers.Dense(1, activation='sigmoid', name='out_' + str(i))(a)) #sigmoid

    model = models.Model(inputs=[image_input, metadata], outputs=outputs)

    return model, base_model


def create_transfer_image_only_model():

    base_model = InceptionV3(weights='imagenet', include_top=False, input_shape=(300, 300, 3), pooling='avg')
    #base_model = VGG16(weights='imagenet',include_top=False,input_shape=(300, 300, 3))
    image_input = layers.Input(shape=(300, 300, 3), name='image')
    x = base_model(image_input)
    x = layers.Dense(256, activation='relu')(x)
    x = layers.Dense(128, activation='relu')(x)
    x = layers.Dropout(.1)(x)
    x = layers.Dense(128, activation='relu')(x)
    x = layers.Dropout(.1)(x)

    outputs = []  # will be throttle, yaw, pitch, roll

    #for i in range(4):
    #    outputs.append(layers.Dense(1, activation='sigmoid', name='out_' + str(i))(z)) #sigmoid
    for i in range(4):
        outputs.append(layers.Dense(1, activation='sigmoid', name='out_' + str(i))(x))

    model = models.Model(inputs=[image_input], outputs=outputs)

    return model, base_model

def create_encoder(img_in):
    x = img_in
    x = layers.Convolution2D(24, (5, 5), strides=(2, 2), activation='relu')(x)
    x = layers.Convolution2D(32, (5, 5), strides=(2, 2), activation='relu')(x)
    #X_shortcut = x
    #X_shortcut = Convolution2D(64, (5, 5), strides=(4, 4), activation='relu')(x)  should take into resnet like skips to improve performance once model becomes deeper
    x = layers.Convolution2D(64, (3, 3), strides=(2, 2), activation='relu')(x)
    x = layers.Convolution2D(64, (3, 3), strides=(2, 2), activation='relu')(x)
    #x = Add()([x, X_shortcut])
    x = layers.Convolution2D(64, (3, 3), strides=(1, 1), activation='relu')(x)
    x = layers.Convolution2D(64, (3, 3), strides=(1, 1), activation='relu')(x)
    x = layers.Flatten(name='flattened')(x)
    x = layers.Dense(100, activation='relu')(x)
    x = layers.Dropout(.1)(x)
    return x

def create_model():  
    input_shape = (300, 300, 3)
    
    img_in = layers.Input(shape=input_shape, name='img_in')

    #targetdistance, pathdistance, headingdelta, speed, altitude, x, y, z
    metadata = layers.Input(shape=(8,), name="path_distance_in")

    x = create_encoder(img_in)
    x = layers.Dense(100, activation='relu')(x)
    x = layers.Dropout(.1)(x)

    y = metadata
    y = layers.Dense(14, activation='relu')(y)
    y = layers.Dense(28, activation='relu')(y)
    y = layers.Dense(56, activation='relu')(y)

    z = layers.concatenate([x, y])
    z = layers.Dense(50, activation='relu')(z)
    z = layers.Dropout(.1)(z)
    z = layers.Dense(50, activation='relu')(z)
    z = layers.Dropout(.1)(z)

    outputs = []  # will be throttle, yaw, pitch, roll

    for i in range(4):
        outputs.append(layers.Dense(1, activation='sigmoid', name='out_' + str(i))(z))

    model = models.Model(inputs=[img_in, metadata], outputs=outputs)

    return model



#model = create_model()]
#model, base_model= create_transfer_model()

#print(base_model.summary())

#dot_img_file = 'model_432.png'
#tf.keras.utils.plot_model(model, to_file=dot_img_file, show_shapes=True)

# %%

